"""PaddleOCR text-extraction service for Storeye.

Responsibilities (keep minimal):
- Initialise PaddleOCR (PaddleX-based OCR, version-aware).
- Extract raw text from an image.
- Return normalized, Storeye-friendly OCR results
  (text + confidence + bounding box [x1, y1, x2, y2]).

This module is ONLY text extraction. It must NOT implement expiry-date
parsing, FEFO, inventory, alerts, product/SKU matching, or any other
business logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("storeye.vision.ocr")


@dataclass
class OCRTextItem:
    """A single detected text region."""

    text: str
    confidence: float
    bbox_xyxy: List[float]  # [x1, y1, x2, y2] pixel coords


@dataclass
class OCRResult:
    """Normalized result of one OCR call."""

    items: List[OCRTextItem] = field(default_factory=list)

    def texts(self) -> List[str]:
        return [it.text for it in self.items]

    def __len__(self) -> int:
        return len(self.items)


class OCRService:
    """PaddleOCR-based text extractor.

    Tested against PaddleOCR 3.7.0 (PaddleX 3.7.2, PaddlePaddle 3.3.1,
    CPU build on Apple Silicon Mac — Paddle does not use MPS directly).

    Example:
        service = OCRService()
        result = service.extract_text(image_bgr)   # numpy (H, W, 3)
        for item in result.items:
            print(item.text, item.confidence, item.bbox_xyxy)
    """

    def __init__(
        self,
        lang: str = "en",
        use_textline_orientation: bool = True,
    ) -> None:
        self.lang = lang
        self.use_textline_orientation = use_textline_orientation
        self._ocr: Any = None
        self.load()

    # ------------------------------------------------------------------
    # Loading / initialisation
    # ------------------------------------------------------------------
    def load(self) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "PaddleOCR is not installed. Run: "
                "pip install paddleocr  (in the Storeye backend env)"
            ) from exc

        try:
            # PaddleOCR 3.x (PaddleX-based). Disable doc orientation and
            # unwarping (not needed for product/package labels); keep
            # textline orientation for rotated/bent text. Runs on CPU on
            # Apple Silicon (Paddle has no MPS backend in this build).
            self._ocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=self.use_textline_orientation,
                lang=self.lang,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialise PaddleOCR: {exc}"
            ) from exc

        logger.info(
            "PaddleOCR initialised | lang=%s | use_textline_orientation=%s",
            self.lang,
            self.use_textline_orientation,
        )

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def extract_text(self, image_bgr: Any) -> OCRResult:
        """Extract text from a BGR image/frame.

        Args:
            image_bgr: numpy array (H, W, 3) in BGR order.

        Returns:
            OCRResult containing one OCRTextItem per detected text region.
        """
        if self._ocr is None:
            raise RuntimeError("PaddleOCR not initialised. Call load() first.")

        import cv2

        # PaddleOCR accepts an image path or a decoded array; pass a BGR
        # ndarray directly (RGB conversion handled internally by PaddleX).
        try:
            raw = self._ocr.predict(image_bgr)
        except Exception as exc:
            raise RuntimeError(f"OCR inference failed: {exc}") from exc

        return self._parse_response(raw)

    def _parse_response(self, raw: Any) -> OCRResult:
        """Convert PaddleOCR 3.x results into normalized OCRTextItems."""
        result = OCRResult()

        # PaddleX predict() returns an iterable of per-batch result dicts.
        results = list(raw) if raw is not None else []

        for res in results:
            if not isinstance(res, dict):
                continue
            texts = res.get("rec_texts", []) or []
            scores = res.get("rec_scores", []) or []
            polys = res.get("rec_polys", []) or []

            for i, t in enumerate(texts):
                text = str(t)
                if not text.strip():
                    continue
                conf = float(scores[i]) if i < len(scores) else 0.0
                bbox = [0.0, 0.0, 0.0, 0.0]
                if i < len(polys) and polys[i] is not None:
                    bbox = self._poly_to_xyxy(polys[i])
                result.items.append(
                    OCRTextItem(text=text, confidence=conf, bbox_xyxy=bbox)
                )
        return result

    @staticmethod
    def _poly_to_xyxy(poly: Any) -> List[float]:
        """Convert a polygon (list of points) to [x1, y1, x2, y2]."""
        try:
            arr = poly
            xs = [float(p[0]) for p in arr]
            ys = [float(p[1]) for p in arr]
            return [min(xs), min(ys), max(xs), max(ys)]
        except Exception:
            return [0.0, 0.0, 0.0, 0.0]

    # ------------------------------------------------------------------
    # Annotation (debug/verification only)
    # ------------------------------------------------------------------
    def annotate(self, image_bgr: Any, result: OCRResult,
                 color=(0, 200, 255), text_color=(200, 0, 0)) -> Any:
        """Draw OCR boxes + text. Returns a new BGR frame."""
        import cv2

        out = image_bgr.copy()
        for it in result.items:
            x1, y1, x2, y2 = (int(v) for v in it.bbox_xyxy)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            label = f"{it.text} ({it.confidence:.2f})"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            top = max(y1 - th - 8, 0)
            cv2.rectangle(out, (x1, top), (min(x1 + tw, out.shape[1] - 1), top + th + 6), color, -1)
            cv2.putText(
                out,
                label,
                (x1, top + th + 3),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                text_color,
                1,
                cv2.LINE_AA,
            )
        return out
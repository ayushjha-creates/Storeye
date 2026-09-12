"""Close-up package OCR pipeline for Smart Batch Intake.

This is the *close-up* OCR path (shopkeeper-assisted). It reuses the existing
PaddleOCR text extractor (`app/services/vision/ocr.py`) and the existing
conservative parser (`app/services/product/expiry_parser.py`) — nothing in the
parser/OCR layer is duplicated or re-implemented.

Pre-OCR quality gate
    Reject images too small or too low-resolution for reliable close-up text
    reading before we even attempt inference ("garbage-in guard").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np

from .errors import ImageDecodeError, OcrUnavailableError

logger = logging.getLogger("storeye.batch_intake.package_ocr")

MAX_IMAGE_BYTES = 15 * 1024 * 1024


@dataclass
class QualityGateConfig:
    """Pre-OCR minimums for a close-up package photo."""

    min_short_side: int = 480
    min_long_side: int = 960


def decode_image_bytes(image_bytes: bytes) -> np.ndarray:
    """Decode raw upload bytes into a BGR numpy array.

    Raises:
        ImageDecodeError: bytes are not a decodable image or exceed the limit.
    """
    if not image_bytes:
        raise ImageDecodeError("Empty image upload.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ImageDecodeError(
            f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB upload limit."
        )
    import cv2

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ImageDecodeError("Upload is not a decodable image.")
    return image


def check_quality(
    image: np.ndarray, config: Optional[QualityGateConfig] = None
) -> List[str]:
    """Return a list of problems (empty = passes the pre-OCR gate)."""
    cfg = config or QualityGateConfig()
    problems: List[str] = []
    if image is None:
        problems.append("Image could not be decoded.")
        return problems
    h, w = int(image.shape[0]), int(image.shape[1])
    short_side = min(h, w)
    long_side = max(h, w)
    if short_side < cfg.min_short_side:
        problems.append(
            f"Image {w}x{h} is too small (short side {short_side}px < "
            f"{cfg.min_short_side}px) for reliable close-up reading."
        )
    if long_side < cfg.min_long_side:
        problems.append(
            f"Image {w}x{h} is too low resolution (long side {long_side}px < "
            f"{cfg.min_long_side}px) for reliable close-up reading."
        )
    return problems


class PackageOCRProcessor:
    """Runs PaddleOCR on a close-up package photo.

    The OCR model is constructed lazily and re-used, so the first scan pays
    the initialisation cost and every later scan does not.
    """

    def __init__(
        self,
        ocr_factory: Optional[Callable[[], object]] = None,
        quality: Optional[QualityGateConfig] = None,
    ) -> None:
        self.ocr_factory = ocr_factory or self._default_ocr_factory
        self.quality = quality or QualityGateConfig()
        self._ocr: Optional[object] = None

    @staticmethod
    def _default_ocr_factory():
        # Imported lazily: constructing OCRService loads the PaddleOCR model.
        from ..vision.ocr import OCRService

        return OCRService()

    def _get_ocr(self):
        if self._ocr is None:
            try:
                self._ocr = self.ocr_factory()
            except Exception as exc:
                raise OcrUnavailableError(
                    "Close-up OCR (PaddleOCR) could not be initialised: "
                    f"{exc}"
                ) from exc
        return self._ocr

    def run(self, image_bgr: np.ndarray) -> Tuple[object, List[str]]:
        """Extract text from a close-up photo.

        Returns:
            (OCRResult, notes). `notes` carries non-fatal messages (e.g. an
            inference hiccup) so a successful barcode match still completes.
        """
        notes: List[str] = []
        try:
            result = self._get_ocr().extract_text(image_bgr)
            if result is None:
                result = _EMPTY_RESULT
        except Exception as exc:  # inference/load failure
            logger.warning("Close-up OCR failed: %s", exc)
            notes.append("OCR could not read this photo; retake it if values are missing.")
            return _EMPTY_RESULT, notes
        return result, notes


def _empty_from_ocr() -> object:
    from ..vision.ocr import OCRResult

    return OCRResult()


_EMPTY_RESULT = _empty_from_ocr()
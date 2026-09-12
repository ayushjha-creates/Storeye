"""OCR + expiry parsing model adapter (EDGE, experimental/opt-in).

Wraps the existing Vision OCRService (PaddleOCR) and the ExpiryParser behind an
injectable interface for the continuous CCTV pipeline. The pipeline runs OCR on
a cadence (not every frame) and feeds the raw text through the ExpiryParser;
when a parse is produced it is reported as EXPIRY_METADATA. Uncertain OCR is
marked low-confidence rather than fabricated.

ARCHITECTURE NOTE (Milestone 17)
--------------------------------
This continuous-camera OCR tap is EXPERIMENTAL and OFF by default
(`PipelineConfig.ocr = False`). It is NOT a source of business truth: text read
from a distant/gorilla-mounted camera is not guaranteed to identify which item
it refers to, and it must never mutate inventory.

The RELIABLE, supported OCR path is **Smart Batch Receiving**
(`app/services/batch_intake/`) — a CLOSE-UP, shopkeeper-assisted package photo
paired with a local barcode decode and the same ExpiryParser, then a
human-confirmed inventory mutation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.product.expiry_parser import ExpiryParser

logger = logging.getLogger("storeye.edge.models.ocr")


@dataclass
class OCRLine:
    text: str
    confidence: float
    bbox_xyxy: List[float]


@dataclass
class ExpiryMetadata:
    expiry_date: Optional[str] = None
    expiry_date_precision: Optional[str] = None
    manufacturing_date: Optional[str] = None
    batch_number: Optional[str] = None
    mrp: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class OCRFrameResult:
    lines: List[OCRLine]
    expiry: Optional[ExpiryMetadata] = None
    status: str = "none"  # "parsed" | "low_confidence" | "none"
    confidence: Optional[float] = None


class OCRModel:
    """Real PaddleOCR + ExpiryParser adapter."""

    def __init__(self, lang: str = "en"):
        from app.services.vision.ocr import OCRService

        self._ocr = OCRService(lang=lang)
        self._parser = ExpiryParser()

    def initialised(self) -> bool:
        return self._ocr._ocr is not None

    def ocr_frame(self, frame) -> OCRFrameResult:
        result = self._ocr.extract_text(frame)
        lines = [OCRLine(it.text, it.confidence, list(it.bbox_xyxy)) for it in result.items]
        return self._finalise(lines)


    def _finalise(self, lines: List[OCRLine]) -> OCRFrameResult:
        if not lines:
            return OCRFrameResult(lines=[], status="none")
        # Parser accepts an iterable of items exposing .text; pass plain lines.
        parsed = self._parser.parse([line.text for line in lines])
        confidence = parsed.confidence
        if not parsed:
            return OCRFrameResult(lines=lines, status="none")
        metadata = ExpiryMetadata(
            expiry_date=parsed.expiry_date.isoformat() if parsed.expiry_date else None,
            expiry_date_precision=parsed.expiry_date_precision,
            manufacturing_date=(
                parsed.manufacturing_date.isoformat() if parsed.manufacturing_date else None
            ),
            batch_number=parsed.batch_number,
            mrp=str(parsed.mrp) if parsed.mrp is not None else None,
            warnings=list(parsed.warnings),
        )
        status = "parsed"
        if confidence is not None and confidence < 0.6:
            status = "low_confidence"
        return OCRFrameResult(lines=lines, expiry=metadata, confidence=confidence, status=status)


class FakeOCR:
    """Deterministic fake OCR for unit tests."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._frame = 0

    def initialised(self) -> bool:
        return True

    def ocr_frame(self, frame) -> OCRFrameResult:
        self._frame += 1
        lines = [
            OCRLine("EXP 12/09/2027", 0.97, [10.0, 10.0, 90.0, 30.0]),
            OCRLine("BATCH AB123", 0.92, [10.0, 40.0, 90.0, 60.0]),
        ]
        expiry = ExpiryMetadata(
            expiry_date="2027-09-12",
            expiry_date_precision="day",
            batch_number="AB123",
        )
        return OCRFrameResult(lines=lines, expiry=expiry, status="parsed")

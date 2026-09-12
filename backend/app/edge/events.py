"""Structured outputs produced by the Edge AI pipeline.

These are the normalized, database-shaped facts that the pipeline emits after
running its models on a frame. They contain NO business logic and NO direct
database writes — a downstream observation writer maps them to the existing
Observation domain model via the ObservationService.

PERSON/PRODUCT events carry anonymous tracking ids and bounding boxes; OCR
events carry raw text and optional parsed expiry metadata. Nothing here ever
mutates inventory, batches, bills or sales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class EventKind(str, Enum):
    PERSON = "PERSON"
    PRODUCT = "PRODUCT"
    TEXT = "TEXT"
    EXPIRY_METADATA = "EXPIRY_METADATA"


@dataclass
class Detection:
    """A single model detection on a frame."""

    class_id: Optional[int] = None
    class_name: Optional[str] = None
    confidence: float = 0.0
    bbox_xyxy: list = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    # Anonymous, session-scoped tracking id (people only). Never an identity.
    track_id: Optional[int] = None


@dataclass
class PersonDetection(Detection):
    track_id: Optional[int] = None


@dataclass
class ProductDetection(Detection):
    # product class/name as detected by the shelf detector (e.g. "Complan").
    pass


@dataclass
class _ExpiryFields:
    expiry_date: Optional[str] = None
    expiry_date_precision: Optional[str] = None
    manufacturing_date: Optional[str] = None
    batch_number: Optional[str] = None
    mrp: Optional[str] = None
    warnings: list = field(default_factory=list)


@dataclass
class EdgeEvent:
    """A single structured observation event emitted by a pipeline tap."""

    kind: EventKind
    camera_id: str
    timestamp: datetime
    frame_number: int
    # Nested payload carrying bbox / track / text / parsed metadata.
    payload: Any = None
    confidence: Optional[float] = None
    source: Optional[str] = None


@dataclass
class OCRText:
    text: str
    confidence: float
    bbox_xyxy: list = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])


@dataclass
class OCRParsed:
    raw_text: str
    text_items: list = field(default_factory=list)  # list[OCRText]
    expiry: Optional[_ExpiryFields] = None
    confidence: Optional[float] = None
    status: str = "parsed"  # "parsed" | "low_confidence" | "none"


# Convenience constructors --------------------------------------------------


def person_event(
    *,
    camera_id: str,
    frame_number: int,
    timestamp: datetime,
    track_id: int,
    confidence: float,
    bbox_xyxy: list,
    class_name: str = "person",
    source: Optional[str] = None,
) -> EdgeEvent:
    person = PersonDetection(
        class_id=0,
        class_name=class_name,
        confidence=confidence,
        bbox_xyxy=bbox_xyxy,
        track_id=track_id,
    )
    return EdgeEvent(
        kind=EventKind.PERSON,
        camera_id=camera_id,
        timestamp=timestamp,
        frame_number=frame_number,
        confidence=confidence,
        payload=person,
        source=source,
    )


def product_event(
    *,
    camera_id: str,
    frame_number: int,
    timestamp: datetime,
    class_name: str,
    confidence: float,
    bbox_xyxy: list,
    source: Optional[str] = None,
) -> EdgeEvent:
    prod = ProductDetection(
        class_name=class_name,
        confidence=confidence,
        bbox_xyxy=bbox_xyxy,
    )
    return EdgeEvent(
        kind=EventKind.PRODUCT,
        camera_id=camera_id,
        timestamp=timestamp,
        frame_number=frame_number,
        confidence=confidence,
        payload=prod,
        source=source,
    )


def text_event(
    *,
    camera_id: str,
    frame_number: int,
    timestamp: datetime,
    text: str,
    confidence: float,
    bbox_xyxy: list,
    source: Optional[str] = None,
) -> EdgeEvent:
    return EdgeEvent(
        kind=EventKind.TEXT,
        camera_id=camera_id,
        timestamp=timestamp,
        frame_number=frame_number,
        confidence=confidence,
        payload=OCRText(text=text, confidence=confidence, bbox_xyxy=bbox_xyxy),
        source=source,
    )


def expiry_event(
    *,
    camera_id: str,
    frame_number: int,
    timestamp: datetime,
    raw_text: str,
    text_items: list,
    expiry: Optional[dict],
    confidence: Optional[float],
    status: str,
    source: Optional[str] = None,
) -> EdgeEvent:
    parsed = OCRParsed(
        raw_text=raw_text,
        text_items=text_items,
        expiry=(_ExpiryFields(**expiry) if expiry else None),
        confidence=confidence,
        status=status,
    )
    return EdgeEvent(
        kind=EventKind.EXPIRY_METADATA,
        camera_id=camera_id,
        timestamp=timestamp,
        frame_number=frame_number,
        confidence=confidence,
        payload=parsed,
        source=source,
    )

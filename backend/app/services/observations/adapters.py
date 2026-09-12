"""Vision adapters — convert existing AI outputs to observation data.

These adapters ONLY translate AI result objects into normalized observation
fields. They do NOT run the AI (no PaddleOCR, no YOLO) and they do NOT persist
anything. Persistence is the ObservationService's job.

They are import-guarded: importing this module must not force the heavy
vision/parser dependencies to load. Each function is defensive about the shape
of the object it receives (duck-typed) so tests can pass simple stand-ins.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence
from datetime import date, datetime, timezone

from app.models import OBS_PRODUCT, OBS_PERSON, OBS_TEXT, OBS_EXPIRY_METADATA


class ObservationDraft:
    """A normalized, not-yet-persisted observation payload.

    Carries enough context for the ObservationService to write a row. Field
    names map directly to Observation model columns.
    """

    __slots__ = (
        "observation_type",
        "store_id",
        "camera_id",
        "product_id",
        "batch_id",
        "track_id",
        "frame_number",
        "source",
        "confidence",
        "bbox",
        "text",
        "observed_at",
        "details",
        "source_observation_id",
    )

    def __init__(
        self,
        *,
        observation_type: str,
        store_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        product_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        track_id: Optional[int] = None,
        frame_number: Optional[int] = None,
        source: Optional[str] = None,
        confidence: Optional[float] = None,
        bbox: Optional[Sequence[float]] = None,
        text: Optional[str] = None,
        observed_at: Optional[datetime] = None,
        details: Optional[dict] = None,
        source_observation_id: Optional[str] = None,
    ) -> None:
        self.observation_type = observation_type
        self.store_id = store_id
        self.camera_id = camera_id
        self.product_id = product_id
        self.batch_id = batch_id
        self.track_id = track_id
        self.frame_number = frame_number
        self.source = source
        self.confidence = confidence
        self.bbox = list(bbox) if bbox is not None else None
        self.text = text
        self.observed_at = observed_at
        self.details = details or None
        self.source_observation_id = source_observation_id

    def to_kwargs(self) -> dict:
        return {
            "observation_type": self.observation_type,
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "product_id": self.product_id,
            "batch_id": self.batch_id,
            "track_id": self.track_id,
            "frame_number": self.frame_number,
            "source": self.source,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "text": self.text,
            "observed_at": self.observed_at,
            "details": self.details,
            "source_observation_id": self.source_observation_id,
        }


def _as_list4(value: Any) -> Optional[list]:
    if value is None:
        return None
    try:
        vals = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    if len(vals) < 4 or any(math.isnan(v) or math.isinf(v) for v in vals):
        return None
    return vals


def _fmt(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def from_shelf_detection(
    detection: Any,
    *,
    source: Optional[str] = None,
    store_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    product_id: Optional[str] = None,
    frame_number: Optional[int] = None,
    observed_at: Optional[datetime] = None,
) -> ObservationDraft:
    """Adapt a ShelfDetector Detection -> PRODUCT observation.

    Note: a shelf detection may NOT map to a store product. `product_id` stays
    None unless the caller has established a match. The adapter never guesses.
    """
    return ObservationDraft(
        observation_type=OBS_PRODUCT,
        store_id=store_id,
        camera_id=camera_id,
        product_id=product_id,
        frame_number=frame_number,
        source=source,
        observed_at=observed_at,
        confidence=getattr(detection, "confidence", None),
        bbox=_as_list4(getattr(detection, "bbox_xyxy", None)),
        details=_build_detection_details(detection),
    )


def from_person_detection(
    detection: Any,
    *,
    source: Optional[str] = None,
    store_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    frame_number: Optional[int] = None,
    observed_at: Optional[datetime] = None,
) -> ObservationDraft:
    """Adapt a PersonDetector Detection -> PERSON observation.

    A bare person detection has no track id yet (tracking assigns it later),
    so track_id is None here.
    """
    return ObservationDraft(
        observation_type=OBS_PERSON,
        source=source,
        store_id=store_id,
        camera_id=camera_id,
        track_id=None,
        frame_number=frame_number,
        confidence=getattr(detection, "confidence", None),
        bbox=_as_list4(getattr(detection, "bbox_xyxy", None)),
        observed_at=observed_at,
        details=_build_detection_details(detection),
    )


def from_tracked_person(
    person: Any,
    *,
    source: Optional[str] = None,
    store_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    frame_number: Optional[int] = None,
    observed_at: Optional[datetime] = None,
) -> ObservationDraft:
    """Adapt a PersonTracker TrackedPerson -> PERSON observation.

    track_id is the anonymous ByteTrack id for THIS session only. It is not an
    identity and must never be treated as one across sessions.
    """
    return ObservationDraft(
        observation_type=OBS_PERSON,
        source=source,
        store_id=store_id,
        camera_id=camera_id,
        track_id=getattr(person, "track_id", None),
        frame_number=frame_number,
        confidence=getattr(person, "confidence", None),
        bbox=_as_list4(getattr(person, "bbox_xyxy", None)),
        observed_at=observed_at,
        details=_build_detection_details(person),
    )


def from_ocr_result(
    ocr_item: Any,
    *,
    source: Optional[str] = None,
    store_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    frame_number: Optional[int] = None,
    observed_at: Optional[datetime] = None,
) -> ObservationDraft:
    """Adapt a single OCRResult item (text/confidence/bbox) -> TEXT observation."""
    return ObservationDraft(
        observation_type=OBS_TEXT,
        source=source,
        store_id=store_id,
        camera_id=camera_id,
        frame_number=frame_number,
        confidence=getattr(ocr_item, "confidence", None),
        bbox=_as_list4(getattr(ocr_item, "bbox_xyxy", None)),
        text=getattr(ocr_item, "text", None),
        observed_at=observed_at,
    )


def from_parsed_metadata(
    metadata: Any,
    *,
    source: Optional[str] = None,
    store_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    source_observation_id: Optional[str] = None,
    observed_at: Optional[datetime] = None,
) -> ObservationDraft:
    """Adapt ParsedProductMetadata -> EXPIRY_METADATA observation.

    Only records what the parser observed. It does NOT create/update a Batch
    (batch creation is the explicit BatchService.create_batch operation).
    """
    details: dict = {}
    for key in (
        "expiry_date",
        "expiry_date_precision",
        "manufacturing_date",
        "manufacturing_date_precision",
        "batch_number",
        "mrp",
    ):
        val = getattr(metadata, key, None)
        if val is not None:
            details[key] = _fmt(val)
    warnings = getattr(metadata, "warnings", None)
    if warnings:
        details["warnings"] = list(warnings)

    return ObservationDraft(
        observation_type=OBS_EXPIRY_METADATA,
        source=source,
        store_id=store_id,
        camera_id=camera_id,
        confidence=getattr(metadata, "confidence", None),
        text=getattr(metadata, "raw_text", None) or None,
        observed_at=observed_at,
        details=details or None,
        source_observation_id=source_observation_id,
    )


def _build_detection_details(detection: Any) -> Optional[dict]:
    class_id = getattr(detection, "class_id", None)
    class_name = getattr(detection, "class_name", None)
    details: dict = {}
    if class_id is not None:
        details["class_id"] = class_id
    if class_name is not None:
        details["class_name"] = class_name
    return details or None
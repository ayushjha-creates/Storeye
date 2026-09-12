"""EdgeEvent -> Observation persistence.

Maps structured EdgeEvents onto the existing ObservationService (PostgreSQL
via SQLAlchemy). Includes per-camera throttling so repetitive detections do not
flood the database.

Product observations carry an AI class label from the shelf detector. This
module applies the EXPLICIT, configurable mapping on Product.ai_classes: a
class that a Storeye product deliberately declares becomes that product's
`product_id` on the observation. Anything unmapped stays product_id=None and is
surfaced upstream as "Unmapped AI class" — the runtime never guesses a mapping.

This module is the ONLY place the Edge runtime talks to the data layer. It
uses the existing ObservationService — it does not bypass the service layer and
it NEVER touches inventory, batches, bills or sales.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product
from app.services.observations.observation_service import ObservationService

from .events import EdgeEvent, EventKind, OCRParsed

logger = logging.getLogger("storeye.edge.writer")


def _uuid_or_none(value: Optional[str]) -> Optional[str]:
    """Return the value only if it is a valid UUID string, else None.

    The runtime may be given non-DB camera ids (e.g. demo/file cameras not tied
    to a `cameras` row). Those cannot be stored as a camera FK, so they are
    dropped to None rather than crashing the worker thread on a UUID parse error.
    """
    if value is None:
        return None
    try:
        UUID(str(value))
        return str(value)
    except (ValueError, AttributeError):
        return None


def _load_class_to_product(session: Session, store_id: Optional[str]) -> Dict[str, str]:
    """Load the store's explicit AI class -> product mapping.

    Reads `products.ai_classes` (a JSONB list of class names) and maps each
    class to its product UUID (string). Deterministic: if two products declare
    the same class, the alphabetically-first SKU wins. Returns an empty dict
    when there is no store context or no mappings.
    """
    mapping: Dict[str, str] = {}
    if store_id is None:
        return mapping
    try:
        stmt = (
            select(Product.id, Product.sku, Product.ai_classes)
            .where(
                Product.store_id == UUID(store_id),
                Product.ai_classes.is_not(None),
            )
            .order_by(Product.sku)
        )
        for pid, _sku, classes in session.execute(stmt):
            for cls in classes or []:
                if isinstance(cls, str) and cls not in mapping:
                    mapping[cls] = str(pid)
    except Exception:  # pragma: no cover - defensive; never block inference
        logger.exception("Failed to load AI class -> product mapping")
    return mapping


class ObservationWriter:
    """Persists EdgeEvents as observations through ObservationService."""

    def __init__(
        self,
        session: Session,
        *,
        store_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        min_gap_seconds: float = 2.0,
    ) -> None:
        self._service = ObservationService(session)
        self._session = session
        self._store_id = _uuid_or_none(store_id)
        self._camera_id = _uuid_or_none(camera_id)
        self._min_gap = min_gap_seconds
        # Per-kind last-write timestamps for throttling.
        self._last_write: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        # Lazy explicit class->product mapping for this writer's store.
        self._class_to_product: Optional[Dict[str, str]] = None

    def _mapped_product_id(self, class_name: Optional[str]) -> Optional[str]:
        if not class_name:
            return None
        if self._class_to_product is None:
            self._class_to_product = _load_class_to_product(self._session, self._store_id)
        return self._class_to_product.get(class_name)

    # ------------------------------------------------------------------
    def _allowed(self, kind: EventKind, now: datetime) -> bool:
        key = kind.value
        last = self._last_write.get(key)
        if last is None:
            self._last_write[key] = now
            return True
        if (now - last).total_seconds() < self._min_gap:
            return False
        self._last_write[key] = now
        return True

    def write(self, events) -> int:
        """Persist events (subject to throttling); return rows written."""
        written = 0
        now = datetime.now(timezone.utc)
        with self._lock:
            for ev in events:
                if not self._allowed(ev.kind, now):
                    continue
                if self._write_one(ev, now):
                    written += 1
        return written

    def close(self) -> None:
        """Release the underlying database session (background-thread hygiene)."""
        session = getattr(self._service, "session", None)
        if session is not None:
            try:
                session.close()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Error closing observation writer session")

    # ------------------------------------------------------------------
    def _write_one(self, ev: EdgeEvent, now: datetime) -> bool:
        """Write one event; if the camera FK is missing, fall back to None."""
        camera_id = self._camera_id or ev.camera_id
        first = self._event_kwargs(ev, now, camera_id)
        method = first.pop("_method")

        def record(kw):
            getattr(self._service, method)(**kw)

        try:
            record(first)
            return True
        except Exception as first_err:
            # If the camera (or store) FK does not match a real DB row, persist
            # without that FK rather than dropping the observation entirely.
            if camera_id:
                try:
                    fallback = dict(first)
                    fallback["camera_id"] = None
                    record(fallback)
                    return True
                except Exception:
                    pass
            logger.warning("Observation write failed for %s: %s", ev.camera_id, first_err)
            return False

    def _event_kwargs(self, ev: EdgeEvent, now: datetime, camera_id) -> dict:
        common = dict(
            store_id=self._store_id,
            camera_id=camera_id,
            frame_number=ev.frame_number,
            source=ev.source,
            observed_at=ev.timestamp,
        )
        if ev.kind == EventKind.PERSON:
            p = ev.payload
            return dict(
                _method="record_person_observation",
                **common,
                track_id=p.track_id,
                confidence=ev.confidence,
                bbox=ev.payload.bbox_xyxy,
            )
        if ev.kind == EventKind.PRODUCT:
            class_name = getattr(ev.payload, "class_name", None)
            return dict(
                _method="record_product_observation",
                **common,
                product_id=self._mapped_product_id(class_name),
                confidence=ev.confidence,
                bbox=ev.payload.bbox_xyxy,
                details={"class_name": class_name},
            )
        if ev.kind == EventKind.TEXT:
            return dict(
                _method="record_text_observation",
                **common,
                text=ev.payload.text,
                confidence=ev.confidence,
                bbox=ev.payload.bbox_xyxy,
            )
        # EXPIRY_METADATA
        parsed: OCRParsed = ev.payload
        return dict(
            _method="record_expiry_metadata_observation",
            store_id=self._store_id,
            camera_id=camera_id,
            source_observation_id=None,
            raw_text=parsed.raw_text,
            confidence=parsed.confidence,
            expiry_date=parsed.expiry.expiry_date if parsed.expiry else None,
            expiry_date_precision=(
                parsed.expiry.expiry_date_precision if parsed.expiry else None
            ),
            manufacturing_date=(
                parsed.expiry.manufacturing_date if parsed.expiry else None
            ),
            batch_number=parsed.expiry.batch_number if parsed.expiry else None,
            mrp=parsed.expiry.mrp if parsed.expiry else None,
            warnings=parsed.expiry.warnings if parsed.expiry else None,
            observed_at=ev.timestamp,
            source=ev.source,
        )

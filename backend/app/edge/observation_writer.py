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
from app.services.product.name_matcher import ProductNameMatcher

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


def _load_name_matcher(
    session: Session, store_id: Optional[str]
) -> Optional[ProductNameMatcher]:
    """Load the store catalog into a conservative OCR-name matcher.

    Returns None when there is no store context, no products, or the query
    fails — OCR then simply records raw text + parsed dates without a product.
    """
    if store_id is None:
        return None
    try:
        stmt = (
            select(Product)
            .where(Product.store_id == UUID(store_id))
            .order_by(Product.name, Product.sku)
        )
        products = list(session.execute(stmt).scalars().all())
    except Exception:  # pragma: no cover - defensive; never block inference
        logger.exception("Failed to load product catalog for OCR name matching")
        return None
    if not products:
        return None
    return ProductNameMatcher.from_products(products)


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
    """Persists EdgeEvents as observations through ObservationService.

    M19: the writer is also the single place where the Edge runtime talks to
    the journey layer. TRACK_ASSOC / ZONE_ENTER / ZONE_EXIT events are piped to
    the optional JourneyService (anonymous global sessions, track associations,
    zone visits, transitions). PERSON observations keep their local track id
    untouched and gain an anonymous `global_person_id` in `details` only.
    """

    def __init__(
        self,
        session: Session,
        *,
        store_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        min_gap_seconds: float = 2.0,
        journey_service=None,
        persist_person_observations: bool = True,
    ) -> None:
        self._service = ObservationService(session)
        self._journey = journey_service
        self._session = session
        self._store_id = _uuid_or_none(store_id)
        self._camera_id = _uuid_or_none(camera_id)
        self._min_gap = min_gap_seconds
        # M29 durable-person policy: False -> PERSON observations are never
        # persisted; all person analytics then live in the hot person-state
        # cache + the minimal journey aggregates. Product/text/expiry and the
        # journey events (track_assoc/zone) are unaffected.
        self._persist_person = persist_person_observations
        # Per-kind last-write timestamps for throttling.
        self._last_write: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        # Lazy explicit class->product mapping for this writer's store.
        self._class_to_product: Optional[Dict[str, str]] = None
        # Lazy catalog matcher for OCR name resolution.
        self._name_matcher: Optional[ProductNameMatcher] = None
        self._name_matcher_loaded = False

    def _mapped_product_id(self, class_name: Optional[str]) -> Optional[str]:
        if not class_name:
            return None
        if self._class_to_product is None:
            self._class_to_product = _load_class_to_product(self._session, self._store_id)
        return self._class_to_product.get(class_name)

    def _match_name_to_product(self, text: Optional[str]):
        """Conservatively match a detected class/prompt name to the catalog."""
        if not text:
            return None
        if not self._name_matcher_loaded:
            self._name_matcher = _load_name_matcher(self._session, self._store_id)
            self._name_matcher_loaded = True
        matcher = self._name_matcher
        if matcher is None:
            return None
        try:
            return matcher.match_lines([str(text)])
        except Exception:  # pragma: no cover - defensive
            logger.exception("Product name matching failed")
            return None

    def _match_ocr_product(self, parsed: OCRParsed):
        """Conservatively resolve a printed product name from OCR text.

        Returns a `NameMatch` or None. Never guesses: an unmatched label stays
        unmatched so the UI can show the raw text as unrecognized.
        """
        if not self._name_matcher_loaded:
            self._name_matcher = _load_name_matcher(self._session, self._store_id)
            self._name_matcher_loaded = True
        matcher = self._name_matcher
        if matcher is None:
            return None
        lines = []
        for item in parsed.text_items or []:
            text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
            if text:
                lines.append(str(text))
        if not lines and parsed.raw_text:
            lines = str(parsed.raw_text).splitlines()
        if not lines:
            return None
        try:
            return matcher.match_lines(lines)
        except Exception:  # pragma: no cover - defensive
            logger.exception("OCR product name matching failed")
            return None

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
    @property
    def persist_person_observations(self) -> bool:
        return self._persist_person

    def _write_one(self, ev: EdgeEvent, now: datetime) -> bool:
        """Write one event; falls back gracefully if a FK is missing."""
        # -------------------------------------------------------------------
        # M29 durable-person policy: when a store opted out of per-frame PERSON
        # observation rows, skip them entirely. The hot person-state cache and
        # the journey aggregates keep carrying their analytics.
        # -------------------------------------------------------------------
        if ev.kind == EventKind.PERSON and not self._persist_person:
            return False

        # -------------------------------------------------------------------
        # M19 journey events — written through JourneyService, not
        # ObservationService. Returns True even when journey_service is absent
        # so the throttle accounting isn't disrupted.
        # -------------------------------------------------------------------
        if ev.kind == EventKind.TRACK_ASSOC:
            return self._write_track_assoc(ev, now)
        if ev.kind == EventKind.ZONE_ENTER:
            return self._write_zone_enter(ev, now)
        if ev.kind == EventKind.ZONE_EXIT:
            return self._write_zone_exit(ev, now)

        # -------------------------------------------------------------------
        # Standard observation path.
        # -------------------------------------------------------------------
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
            details: dict = {}
            # M19: carry the anonymous global id + reid confidence + zone in
            # the observation details for downstream journey queries.
            gid = getattr(p, "global_person_id", None)
            if gid is not None:
                details["global_person_id"] = gid
            reid_conf = getattr(p, "reid_confidence", None)
            if reid_conf is not None:
                details["reid_confidence"] = reid_conf
            zone = getattr(p, "zone_id", None)
            if zone is not None:
                details["zone_id"] = zone
            bbox_norm = getattr(p, "bbox_norm", None)
            if bbox_norm:
                details["bbox_norm"] = list(bbox_norm)
            return dict(
                _method="record_person_observation",
                **common,
                track_id=p.track_id,
                confidence=ev.confidence,
                bbox=ev.payload.bbox_xyxy,
                details=details or None,
            )
        if ev.kind == EventKind.PRODUCT:
            class_name = getattr(ev.payload, "class_name", None)
            product_id = self._mapped_product_id(class_name)
            details: dict = {"class_name": class_name}
            # Open-vocabulary detections are named by their text prompt, so an
            # exact class->product mapping often misses. Fall back to the same
            # conservative catalog name matcher used for OCR labels.
            if product_id is None:
                match = self._match_name_to_product(class_name)
                if match is not None:
                    product_id = _uuid_or_none(match.product_id)
                    details["recognized_product_name"] = match.product_name
                    details["label_match_score"] = match.score
            bbox_norm = getattr(ev.payload, "bbox_norm", None)
            if bbox_norm:
                details["bbox_norm"] = list(bbox_norm)
            return dict(
                _method="record_product_observation",
                **common,
                product_id=product_id,
                confidence=ev.confidence,
                bbox=ev.payload.bbox_xyxy,
                details=details,
            )
        if ev.kind == EventKind.TEXT:
            return dict(
                _method="record_text_observation",
                **common,
                text=ev.payload.text,
                confidence=ev.confidence,
                bbox=ev.payload.bbox_xyxy,
            )
        # EXPIRY_METADATA — also resolves the printed product name conservatively
        # against this store's catalog. Unmatched text is still recorded, with
        # no product attached.
        parsed: OCRParsed = ev.payload
        match = self._match_ocr_product(parsed)
        details_extra: dict = {}
        product_id = None
        if match is not None:
            product_id = _uuid_or_none(match.product_id)
            details_extra["recognized_product_name"] = match.product_name
            details_extra["label_match_score"] = match.score
            details_extra["matched_label"] = match.matched_text
            if match.selling_price is not None:
                details_extra["catalog_price"] = match.selling_price
        return dict(
            _method="record_expiry_metadata_observation",
            store_id=self._store_id,
            camera_id=camera_id,
            source_observation_id=None,
            product_id=product_id,
            details_extra=details_extra or None,
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

    # ------------------------------------------------------------------
    # M19 — journey persistence (anonymous global sessions / visits).
    # These write ONLY through JourneyService and NEVER through
    # ObservationService, which stays observably pure.
    # ------------------------------------------------------------------
    def _write_track_assoc(self, ev: EdgeEvent, now: datetime) -> bool:
        if self._journey is None:
            return True
        gid = getattr(ev.payload, "global_person_id", None)
        confidence = getattr(ev.payload, "association_confidence", None) or "UNKNOWN"
        if not gid or not self._store_id:
            return False
        try:
            self._journey.upsert_track_association(
                store_id=self._store_id,
                global_person_id=gid,
                camera_id=self._camera_id or ev.camera_id,
                track_id=int(ev.payload.track_id or 0),
                confidence=confidence,
                timestamp=ev.timestamp,
            )
            return True
        except Exception:  # pragma: no cover - defensive
            logger.warning("Journey track_assoc write failed for %s", ev.camera_id)
            return False

    def _write_zone_enter(self, ev: EdgeEvent, now: datetime) -> bool:
        if self._journey is None:
            return True
        if not self._store_id:
            return False
        confidence = getattr(ev.payload, "association_confidence", None) or "UNKNOWN"
        try:
            self._journey.open_zone_visit(
                store_id=self._store_id,
                global_person_id=ev.payload.global_person_id,
                zone_id=ev.payload.zone_id,
                camera_id=self._camera_id or ev.camera_id,
                timestamp=ev.timestamp,
                confidence=confidence,
            )
            return True
        except Exception:  # pragma: no cover - defensive
            logger.warning("Journey zone_enter write failed for %s", ev.camera_id)
            return False

    def _write_zone_exit(self, ev: EdgeEvent, now: datetime) -> bool:
        if self._journey is None:
            return True
        if not self._store_id:
            return False
        try:
            self._journey.close_zone_visit(
                store_id=self._store_id,
                global_person_id=ev.payload.global_person_id,
                zone_id=ev.payload.zone_id,
                timestamp=ev.timestamp,
            )
            return True
        except Exception:  # pragma: no cover - defensive
            logger.warning("Journey zone_exit write failed for %s", ev.camera_id)
            return False

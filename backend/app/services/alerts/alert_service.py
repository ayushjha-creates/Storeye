"""AlertService — create, deduplicate, transition, and query alerts (M16).

Alerts are informational/actionable notifications. This service NEVER mutates
inventory, inventory_movements, batches, bills or sales: its only persistence
effects are `alerts` rows (plus their timestamps/metadata).

DEDUPLICATION
-------------
For the same (store_id, alert_type, product_id, shelf_id, camera_id) context an
existing OPEN or ACKNOWLEDGED alert is UPDATED in place:
    * last_detected_at           -> new detection time
    * confidence                 -> latest confidence where appropriate
    * details / evidence         -> merged with the newest evidence
This is deterministic: repeated camera frames never create hundreds of identical
alerts. RESOLVED / DISMISSED alerts are terminal — when the same condition
appears again later, a NEW alert is created.

LIFECYCLE (domain-validated)
----------------------------
    OPEN -> ACKNOWLEDGED | RESOLVED | DISMISSED
    ACKNOWLEDGED -> RESOLVED | DISMISSED
    RESOLVED / DISMISSED -> (none)  -> InvalidStatusTransitionError (422)

TRANSACTIONS
------------
Each public mutation commits its own transaction and rolls back on any failure.
Batch evaluation (AlertRuleEngine.evaluate) commits once at the end so partial
failures never leave half-written alert state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    ALLOWED_TRANSITIONS,
    SEV_MEDIUM,
    STATUS_ACKNOWLEDGED,
    STATUS_DISMISSED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    VALID_ALERT_TYPES,
    VALID_SEVERITIES,
)

from .errors import (
    EntityNotFoundError,
    InvalidStatusTransitionError,
    ValidationError,
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class AlertService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Create / dedup
    # ------------------------------------------------------------------
    def create_alert(
        self,
        *,
        store_id: UUID,
        alert_type: str,
        severity: str,
        title: str,
        message: Optional[str] = None,
        camera_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        shelf_id: Optional[UUID] = None,
        confidence: Optional[float] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        detected_at: Optional[datetime] = None,
        details: Optional[dict] = None,
    ) -> Tuple[Alert, bool]:
        """Upsert an alert. Returns (alert, created). Commits."""
        alert, created = self._upsert_alert(
            store_id=store_id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            camera_id=camera_id,
            product_id=product_id,
            shelf_id=shelf_id,
            confidence=confidence,
            source_type=source_type,
            source_id=source_id,
            detected_at=detected_at,
            details=details,
        )
        self._commit()
        return alert, created

    def _upsert_alert(
        self,
        *,
        store_id: UUID,
        alert_type: str,
        severity: str,
        title: str,
        message: Optional[str] = None,
        camera_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        shelf_id: Optional[UUID] = None,
        confidence: Optional[float] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        detected_at: Optional[datetime] = None,
        details: Optional[dict] = None,
    ) -> Tuple[Alert, bool]:
        """Internal upsert (no commit) used by both public create and rule bulk
        evaluation. Applies deterministic deduplication (see module docstring)."""
        self._validate_inputs(
            alert_type=alert_type,
            severity=severity,
            title=title,
            severity_optional=False,
        )
        now = detected_at or now_utc()

        existing = self._existing_open(store_id, alert_type, product_id, camera_id, shelf_id)
        if existing is not None:
            existing.last_detected_at = now
            if confidence is not None:
                existing.confidence = confidence
            existing.severity = severity
            existing.title = title
            if message is not None:
                existing.message = message
            if source_type is not None:
                existing.source_type = source_type
            if source_id is not None:
                existing.source_id = source_id
            existing.details = self._merge_details(existing.details, details)
            return existing, False

        alert = Alert(
            store_id=store_id,
            camera_id=camera_id,
            product_id=product_id,
            shelf_id=shelf_id,
            alert_type=alert_type,
            severity=severity,
            status=STATUS_OPEN,
            title=title,
            message=message,
            confidence=confidence,
            source_type=source_type,
            source_id=source_id,
            first_detected_at=now,
            last_detected_at=now,
            details=details,
        )
        self.session.add(alert)
        return alert, True

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def query_alerts(
        self,
        *,
        store_id: Optional[UUID] = None,
        camera_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        shelf_id: Optional[UUID] = None,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Alert], int]:
        """Paged alert query (filters evaluated in PostgreSQL)."""
        if alert_type is not None and alert_type not in VALID_ALERT_TYPES:
            raise ValidationError(
                f"alert_type must be one of {sorted(VALID_ALERT_TYPES)}, got {alert_type!r}"
            )
        if status is not None and status not in ALLOWED_TRANSITIONS:
            raise ValidationError(f"status must be one of {sorted(ALLOWED_TRANSITIONS)}")
        if severity is not None and severity not in VALID_SEVERITIES:
            raise ValidationError(f"severity must be one of {sorted(VALID_SEVERITIES)}")

        conds = self._filters(
            store_id=store_id,
            camera_id=camera_id,
            product_id=product_id,
            shelf_id=shelf_id,
            alert_type=alert_type,
            severity=severity,
            status=status,
            created_from=created_from,
            created_to=created_to,
        )
        base = select(Alert).where(*conds)
        total = int(self.session.scalar(select(func.count()).select_from(base.subquery())))
        items = list(
            self.session.scalars(
                base.order_by(Alert.last_detected_at.desc())
                .limit(int(limit))
                .offset(int(offset))
            )
        )
        return items, total

    def get(self, alert_id: UUID) -> Optional[Alert]:
        return self.session.get(Alert, alert_id)

    def get_or_404(self, alert_id: UUID) -> Alert:
        alert = self.get(alert_id)
        if alert is None:
            raise EntityNotFoundError("Alert not found")
        return alert

    # ------------------------------------------------------------------
    # Lifecycle transitions (domain-validated)
    # ------------------------------------------------------------------
    def change_status(self, alert: Alert, new_status: str, *, at: Optional[datetime] = None) -> Alert:
        if new_status not in ALLOWED_TRANSITIONS:
            raise InvalidStatusTransitionError(
                f"Unknown alert status {new_status!r}"
            )
        allowed = ALLOWED_TRANSITIONS.get(alert.status, set())
        if new_status not in allowed:
            raise InvalidStatusTransitionError(
                f"Cannot transition alert from {alert.status} to {new_status} "
                f"(allowed: {sorted(allowed) or 'none'})"
            )
        now = at or now_utc()
        alert.status = new_status
        if new_status == STATUS_ACKNOWLEDGED:
            alert.acknowledged_at = now
        elif new_status == STATUS_RESOLVED:
            alert.resolved_at = now
        elif new_status == STATUS_DISMISSED:
            alert.dismissed_at = now
        self._commit()
        return alert

    def acknowledge(self, alert: Alert, *, at: Optional[datetime] = None) -> Alert:
        return self.change_status(alert, STATUS_ACKNOWLEDGED, at=at)

    def resolve(self, alert: Alert, *, at: Optional[datetime] = None) -> Alert:
        return self.change_status(alert, STATUS_RESOLVED, at=at)

    def dismiss(self, alert: Alert, *, at: Optional[datetime] = None) -> Alert:
        return self.change_status(alert, STATUS_DISMISSED, at=at)

    def update_fields(
        self,
        alert: Alert,
        *,
        title: Optional[str] = None,
        message: Optional[str] = None,
        severity: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> Alert:
        """Metadata-only update; status is never changed here."""
        if title is not None:
            self._validate_inputs(alert_type=alert.alert_type, severity=alert.severity, title=title)
            alert.title = title
        if message is not None:
            alert.message = message
        if severity is not None:
            self._validate_inputs(
                alert_type=alert.alert_type, severity=severity, title=alert.title
            )
            alert.severity = severity
        if details is not None:
            alert.details = details
        self._commit()
        return alert

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _validate_inputs(
        self, *, alert_type: str, severity: str, title: str, severity_optional: bool = True
    ) -> None:
        if not title or not title.strip():
            raise ValidationError("title must not be empty")
        if alert_type not in VALID_ALERT_TYPES:
            raise ValidationError(
                f"alert_type must be one of {sorted(VALID_ALERT_TYPES)}, got {alert_type!r}"
            )
        if (not severity_optional and not severity) or (
            severity is not None and severity not in VALID_SEVERITIES
        ):
            raise ValidationError(f"severity must be one of {sorted(VALID_SEVERITIES)}")

    def _existing_open(
        self,
        store_id: UUID,
        alert_type: str,
        product_id: Optional[UUID],
        camera_id: Optional[UUID],
        shelf_id: Optional[UUID],
    ) -> Optional[Alert]:
        """Deterministic dedup: an OPEN/ACKNOWLEDGED alert with the same
        (store, type, product, shelf, camera) context is updated, not duplicated."""
        conds = [
            Alert.store_id == store_id,
            Alert.alert_type == alert_type,
            Alert.status.in_([STATUS_OPEN, STATUS_ACKNOWLEDGED]),
        ]
        conds.append(self._null_safe_eq(Alert.product_id, product_id))
        conds.append(self._null_safe_eq(Alert.camera_id, camera_id))
        conds.append(self._null_safe_eq(Alert.shelf_id, shelf_id))
        return self.session.scalar(select(Alert).where(*conds))

    @staticmethod
    def _null_safe_eq(column, value):
        if value is None:
            return column.is_(None)
        return column == value

    @staticmethod
    def _merge_details(existing: Optional[dict], new: Optional[dict]) -> Optional[dict]:
        if not existing:
            return dict(new) if new else None
        if not new:
            return existing
        merged = dict(existing)
        merged.update(new)
        return merged

    @staticmethod
    def _filters(
        *,
        store_id: Optional[UUID],
        camera_id: Optional[UUID],
        product_id: Optional[UUID],
        shelf_id: Optional[UUID],
        alert_type: Optional[str],
        severity: Optional[str],
        status: Optional[str],
        created_from: Optional[datetime],
        created_to: Optional[datetime],
    ) -> list:
        conds = []
        if store_id is not None:
            conds.append(Alert.store_id == store_id)
        if camera_id is not None:
            conds.append(Alert.camera_id == camera_id)
        if product_id is not None:
            conds.append(Alert.product_id == product_id)
        if shelf_id is not None:
            conds.append(Alert.shelf_id == shelf_id)
        if alert_type is not None:
            conds.append(Alert.alert_type == alert_type)
        if severity is not None:
            conds.append(Alert.severity == severity)
        if status is not None:
            conds.append(Alert.status == status)
        if created_from is not None:
            conds.append(Alert.first_detected_at >= created_from)
        if created_to is not None:
            conds.append(Alert.first_detected_at <= created_to)
        return conds

    def _commit(self) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise


DEFAULT_ALERT_SEVERITY = SEV_MEDIUM
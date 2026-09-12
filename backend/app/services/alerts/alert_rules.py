"""AlertRuleEngine — turn EXISTING intelligence results into alerts (M16).

RULES (reuse, never re-run inference)
-------------------------------------
    SHORTAGE             ProductIntelligenceRow.comparison_status == POSSIBLE_SHORTAGE
                         and row confidence >= alert_confidence_threshold
    SURPLUS              ProductIntelligenceRow.comparison_status == POSSIBLE_SURPLUS
                         and row confidence >= alert_confidence_threshold
    MISPLACEMENT         MisplacementService row (planogram-based foundation; only
                         mapped products on shelves with expectations)
    LOW_SHELF_OCCUPANCY  ShelfIntelligenceRow.detection_status == LOW_VISIBLE
                         (UNKNOWN is NEVER an alert — no evidence)
    REVIEW_REQUIRED      persisted ReconciliationResult.status == REC_REVIEW in the
                         window (the layer's explicit human-review signal)
    EXPIRY               existing batch expiry date reaching the configured
                         warning window (ExpiryIntelligence reuses Batch data)
    CAMERA_OFFLINE       domain/API foundation: an ACTIVE camera with no
                         observation in `camera_stale_minutes` (a deterministic,
                         simulated stale-heartbeat proxy — NOT a hardware check;
                         documented limitation in the milestone doc)

NOTHING here runs YOLO/PaddleOCR. Nothing here mutates inventory, batches,
bills or sales. Evaluation only reads intelligence and writes/updates `alerts`
rows atomically (one commit at the end; rollback on any failure).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    ALERT_CAMERA_OFFLINE,
    ALERT_EXPIRY,
    ALERT_LOW_SHELF_OCCUPANCY,
    ALERT_MISPLACEMENT,
    ALERT_REVIEW_REQUIRED,
    ALERT_SHORTAGE,
    ALERT_SURPLUS,
    Camera,
    Observation,
    Product,
    REC_REVIEW,
    ReconciliationResult,
    SEV_CRITICAL,
    SEV_HIGH,
    SEV_LOW,
    SEV_MEDIUM,
)
from app.services.intelligence import (
    COMP_SHORTAGE,
    COMP_SURPLUS,
    EXPIRY_STATUS_EXPIRED,
    EXPIRY_STATUS_EXPIRING_SOON,
    EXPIRY_STATUS_MONTH,
    ExpiryIntelligence,
    MisplacementService,
    ProductIntelligenceService,
    SHELF_STATE_LOW,
    ShelfIntelligenceService,
)

from .alert_service import AlertService, now_utc


@dataclass
class AlertRuleResult:
    evaluated_at: datetime = field(default_factory=now_utc)
    store_id: Optional[UUID] = None
    hours: int = 24
    generated: int = 0  # newly created alerts
    updated: int = 0  # deduplicated on OPEN/ACKNOWLEDGED
    skipped: int = 0  # evaluated but below threshold / insufficient evidence
    alerts: List[Alert] = field(default_factory=list)


class AlertRuleEngine:
    """Evaluate existing intelligence and upsert deterministic alerts."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def evaluate(
        self,
        *,
        store_id: UUID,
        camera_id: Optional[UUID] = None,
        min_confidence: float = 0.5,
        alert_confidence_threshold: float = 0.5,
        hours: int = 24,
        expiry_warning_days: Optional[int] = None,
        camera_stale_minutes: int = 60,
        reference_date: Optional[object] = None,
    ) -> AlertRuleResult:
        """Evaluate existing intelligence, deduplicate, and return affected alerts."""
        window = min(max(int(hours), 1), 24 * 7)
        svc = AlertService(self.session)
        result = AlertRuleResult(store_id=store_id, hours=window)

        try:
            self._evaluate_shortage_surplus(
                svc, result, store_id=store_id, camera_id=camera_id,
                min_confidence=min_confidence, hours=window,
                threshold=alert_confidence_threshold,
            )
            self._evaluate_misplacement(
                svc, result, store_id=store_id, camera_id=camera_id,
                min_confidence=min_confidence, hours=window,
            )
            self._evaluate_low_shelf_occupancy(
                svc, result, store_id=store_id, camera_id=camera_id,
                min_confidence=min_confidence, hours=window,
            )
            self._evaluate_review_required(
                svc, result, store_id=store_id, camera_id=camera_id, hours=window,
            )
            self._evaluate_expiry(
                svc, result, store_id=store_id,
                warning_days=expiry_warning_days, reference_date=reference_date,
            )
            self._evaluate_camera_offline(
                svc, result, store_id=store_id, camera_id=camera_id,
                stale_minutes=camera_stale_minutes,
            )
            # One transaction: alert evaluation is all-or-nothing.
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return result

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------
    def _evaluate_shortage_surplus(self, svc, result, *, store_id, camera_id,
                                   min_confidence, hours, threshold) -> None:
        rows = ProductIntelligenceService(self.session).products(
            store_id=store_id, camera_id=camera_id,
            min_confidence=min_confidence, hours=hours,
        )
        for r in rows:
            if not r.mapped or r.product_id is None or r.database_quantity is None:
                continue
            target = None
            if r.comparison_status == COMP_SHORTAGE:
                target = ALERT_SHORTAGE
            elif r.comparison_status == COMP_SURPLUS:
                target = ALERT_SURPLUS
            if target is None:
                continue
            if r.confidence is None or r.confidence < threshold:
                result.skipped += 1  # insufficient AI evidence -> no alert
                continue
            db_qty = r.database_quantity
            diff = r.difference or 0
            if db_qty <= 0 and diff == 0:
                continue
            if target == ALERT_SHORTAGE:
                fraction = (-diff) / db_qty if db_qty > 0 else 1.0
                severity = (
                    SEV_CRITICAL if fraction >= 0.5
                    else SEV_HIGH if fraction >= 0.2
                    else SEV_MEDIUM
                )
                title = f"Possible shortage: {r.product_name} ({r.sku})"
                message = (
                    f"AI sees {r.visible_count} visible on camera {r.camera_name or '?'}; "
                    f"inventory records {db_qty}. Informational — review before any "
                    f"inventory adjustment."
                )
            else:
                fraction = diff / db_qty if db_qty > 0 else 1.0
                severity = (
                    SEV_HIGH if fraction >= 0.5
                    else SEV_MEDIUM if fraction >= 0.2
                    else SEV_LOW
                )
                title = f"Possible surplus: {r.product_name} ({r.sku})"
                message = (
                    f"AI sees {r.visible_count} visible on camera {r.camera_name or '?'}; "
                    f"inventory records {db_qty}. Informational — review before any "
                    f"inventory adjustment."
                )
            details = {
                "source": "product_intelligence",
                "status": r.comparison_status,
                "database_quantity": db_qty,
                "ai_observed_quantity": r.visible_count,
                "difference": diff,
                "counting_rule": r.counting_rule,
                "ai_class": r.ai_class,
                "camera_id": str(r.camera_id) if r.camera_id else None,
                "confidence": r.confidence,
            }
            alert, created = svc._upsert_alert(
                store_id=store_id, alert_type=target, severity=severity,
                title=title, message=message,
                camera_id=r.camera_id, product_id=r.product_id, shelf_id=None,
                confidence=r.confidence, source_type="product_intelligence",
                details=details,
            )
            self._tally(result, alert, created)

    def _evaluate_misplacement(self, svc, result, *, store_id, camera_id,
                               min_confidence, hours) -> None:
        rows = MisplacementService(self.session).misplacements(
            store_id=store_id, camera_id=camera_id,
            min_confidence=min_confidence, hours=hours,
        )
        for m in rows:
            if m.product_id is None:
                continue  # unmapped -> never guessed
            shelf_id = self._shelf_id_by_code(store_id, m.shelf_code)
            expected = self._expected_product_names(store_id, shelf_id)
            details = {
                "source": "shelf_intelligence",
                "expected_product": ", ".join(sorted(expected)) if expected else "no planogram expectation",
                "detected_product": m.product_name,
                "ai_class": m.ai_class,
                "shelf_code": m.shelf_code,
                "shelf_id": str(shelf_id) if shelf_id else None,
                "planogram_id": self._active_planogram_id(store_id),
                "visible_count": m.visible_count,
                "confidence": m.confidence,
            }
            title = f"Possible misplacement: {m.product_name} on shelf {m.shelf_code}"
            message = (
                f"AI detected {m.product_name or m.ai_class} visibly on a shelf whose "
                f"planogram expects other products. Informational — confirm physical "
                f"placement before moving anything."
            )
            alert, created = svc._upsert_alert(
                store_id=store_id, alert_type=ALERT_MISPLACEMENT,
                severity=SEV_LOW, title=title, message=message,
                camera_id=m.camera_id, product_id=m.product_id, shelf_id=shelf_id,
                confidence=m.confidence, source_type="shelf_intelligence",
                details=details,
            )
            self._tally(result, alert, created)

    def _evaluate_low_shelf_occupancy(self, svc, result, *, store_id, camera_id,
                                      min_confidence, hours) -> None:
        rows = ShelfIntelligenceService(self.session).shelves(
            store_id=store_id, camera_id=camera_id,
            min_confidence=min_confidence, hours=hours,
        )
        for s in rows:
            # UNKNOWN means no evidence -> explicitly NEVER an alert.
            if s.detection_status != SHELF_STATE_LOW:
                continue
            pct = s.occupied_pct if s.occupied_pct is not None else 0
            severity = SEV_MEDIUM if pct < 15 else SEV_LOW
            details = {
                "source": "shelf_intelligence",
                "shelf_code": s.shelf_code,
                "region_label": s.region_label,
                "detection_status": s.detection_status,
                "estimated_visible_occupancy": s.estimated_visible_occupancy,
                "occupied_pct": pct,
                "camera_id": str(s.camera_id) if s.camera_id else None,
            }
            title = f"Shelf {s.shelf_code} occupancy is low"
            message = (
                f"AI-estimated visible occupancy is {pct}% (informational; not stock). "
                f"Review stock placement for this shelf."
            )
            alert, created = svc._upsert_alert(
                store_id=store_id, alert_type=ALERT_LOW_SHELF_OCCUPANCY,
                severity=severity, title=title, message=message,
                camera_id=s.camera_id, product_id=None, shelf_id=s.shelf_id,
                confidence=s.mean_confidence, source_type="shelf_intelligence",
                details=details,
            )
            self._tally(result, alert, created)

    def _evaluate_review_required(self, svc, result, *, store_id, camera_id, hours) -> None:
        end = now_utc()
        start = end - timedelta(hours=hours)
        stmt = select(ReconciliationResult).where(
            ReconciliationResult.store_id == store_id,
            ReconciliationResult.status == REC_REVIEW,
            ReconciliationResult.observation_window_end >= start,
            ReconciliationResult.observation_window_start <= end,
        )
        if camera_id is not None:
            stmt = stmt.where(ReconciliationResult.camera_id == camera_id)
        results = list(self.session.scalars(stmt))
        names = self._product_names({r.product_id for r in results})
        for r in results:
            label = names.get(r.product_id, str(r.product_id))
            details = {
                "source": "reconciliation",
                "status": r.status,
                "database_quantity": r.database_quantity,
                "ai_observed_quantity": r.ai_observed_quantity,
                "difference": r.difference,
                "observation_window_start": r.observation_window_start.isoformat(),
                "observation_window_end": r.observation_window_end.isoformat(),
                "counting_rule": (r.details or {}).get("counting_rule"),
            }
            title = f"Review required: {label}"
            message = (
                "No reliable AI evidence for this product in the window. The "
                "reconciliation layer explicitly asks a human to verify stock."
            )
            alert, created = svc._upsert_alert(
                store_id=store_id, alert_type=ALERT_REVIEW_REQUIRED,
                severity=SEV_LOW, title=title, message=message,
                camera_id=r.camera_id, product_id=r.product_id, shelf_id=None,
                confidence=r.confidence, source_type="reconciliation",
                source_id=str(r.id), details=details,
            )
            self._tally(result, alert, created)

    def _evaluate_expiry(self, svc, result, *, store_id, warning_days, reference_date) -> None:
        insights = ExpiryIntelligence(self.session).evaluate(
            store_id=store_id, reference_date=reference_date, warning_days=warning_days,
        )
        for ins in insights:
            if ins.status not in (
                EXPIRY_STATUS_EXPIRED,
                EXPIRY_STATUS_EXPIRING_SOON,
                EXPIRY_STATUS_MONTH,
            ):
                continue
            if ins.status == EXPIRY_STATUS_EXPIRED:
                severity = SEV_HIGH
                title = f"Expired batch: {ins.name}"
                message = (
                    f"Batch {ins.batch_number or 'n/a'} of {ins.name} is past its "
                    f"expiry date ({ins.expiry_date}). Review before selling or moving."
                )
            else:
                severity = SEV_MEDIUM
                title = f"Batch expiring soon: {ins.name}"
                message = (
                    f"Batch {ins.batch_number or 'n/a'} of {ins.name} expires "
                    f"{ins.expiry_date} (warning window {ins.warning_days} days). "
                    f"Review stock rotation."
                )
            details = {
                "source": "expiry_intelligence",
                "status": ins.status,
                "batch_id": str(ins.batch_id),
                "sku": ins.sku,
                "expiry_date": ins.expiry_date.isoformat() if ins.expiry_date else None,
                "expiry_date_precision": ins.expiry_date_precision,
                "warning_days": ins.warning_days,
                "days_until_expiry": ins.days_until_expiry,
            }
            alert, created = svc._upsert_alert(
                store_id=store_id, alert_type=ALERT_EXPIRY,
                severity=severity, title=title, message=message,
                camera_id=None, product_id=ins.product_id, shelf_id=None,
                confidence=None, source_type="expiry_intelligence",
                source_id=str(ins.batch_id), details=details,
            )
            self._tally(result, alert, created)

    def _evaluate_camera_offline(self, svc, result, *, store_id, camera_id,
                                 stale_minutes) -> None:
        """Domain/API foundation for camera-offline alerts.

        Uses a deterministic SIMULATED stale-heartbeat condition derived from
        persisted observations (the edge runtime writes observations when it
        processes frames). This is NOT a hardware/process health check — that is
        documented as a limitation. An active camera with no observation in the
        last `stale_minutes` is flagged.
        """
        stmt = select(Camera).where(
            Camera.store_id == store_id, Camera.is_active.is_(True)
        )
        if camera_id is not None:
            stmt = stmt.where(Camera.id == camera_id)
        cameras = list(self.session.scalars(stmt))
        threshold = now_utc() - timedelta(minutes=int(stale_minutes))

        last_by_cam = dict(
            self.session.execute(
                select(Observation.camera_id, func.max(Observation.observed_at))
                .where(Observation.camera_id.in_([c.id for c in cameras]), Observation.camera_id.is_not(None))
                .group_by(Observation.camera_id)
            ).all()
        ) if cameras else {}

        for cam in cameras:
            last = last_by_cam.get(cam.id)
            is_stale = last is None or last < threshold
            if not is_stale:
                continue
            details = {
                "source": "camera_status",
                "proxy": "observations-based stale heartbeat (simulated foundation; not a hardware check)",
                "last_observed_at": last.isoformat() if last else None,
                "stale_minutes": stale_minutes,
            }
            title = f"Camera offline or idle: {cam.name}"
            message = (
                f"No AI observations recorded in the last {stale_minutes} minutes. "
                "This is a simulated heartbeat proxy, not a hardware connectivity check."
            )
            alert, created = svc._upsert_alert(
                store_id=store_id, alert_type=ALERT_CAMERA_OFFLINE,
                severity=SEV_MEDIUM, title=title, message=message,
                camera_id=cam.id, product_id=None, shelf_id=None,
                confidence=None, source_type="camera_status", details=details,
            )
            self._tally(result, alert, created)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _tally(result, alert, created) -> None:
        if created:
            result.generated += 1
        else:
            result.updated += 1
        result.alerts.append(alert)

    def _shelf_id_by_code(self, store_id: UUID, code: str) -> Optional[UUID]:
        from app.models import Shelf

        s = self.session.scalar(
            select(Shelf).where(Shelf.store_id == store_id, Shelf.code == code)
        )
        return s.id if s else None

    def _active_planogram_id(self, store_id: UUID) -> Optional[str]:
        from app.models import Planogram

        p = self.session.scalar(
            select(Planogram).where(
                Planogram.store_id == store_id, Planogram.is_active.is_(True)
            )
        )
        return str(p.id) if p else None

    def _expected_product_names(self, store_id: UUID, shelf_id: Optional[UUID]) -> List[str]:
        if shelf_id is None:
            return []
        from app.models import Planogram, PlanogramItem

        stmt = (
            select(Product.name)
            .join(PlanogramItem, PlanogramItem.product_id == Product.id)
            .join(Planogram, Planogram.id == PlanogramItem.planogram_id)
            .where(
                Planogram.store_id == store_id,
                Planogram.is_active.is_(True),
                PlanogramItem.shelf_id == shelf_id,
                PlanogramItem.expected_facings > 0,
            )
        )
        return list(self.session.scalars(stmt))

    def _product_names(self, product_ids) -> dict:
        if not product_ids:
            return {}
        rows = self.session.execute(
            select(Product.id, Product.name).where(Product.id.in_([p for p in product_ids if p]))
        )
        return {pid: name for pid, name in rows}
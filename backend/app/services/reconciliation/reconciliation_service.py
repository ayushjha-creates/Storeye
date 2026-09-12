"""ReconciliationService — compare AI observations against inventory.

This service operates ONLY on persisted observation data (Milestone 8) and
recorded inventory. It NEVER imports YOLO/PaddleOCR or the expiry parser.

IMPORTANT GUARANTEE
-------------------
Running reconciliation produces ReconciliationResult rows and nothing else.
It does NOT:
    * update inventory.quantity
    * create inventory movements
    * create batches
    * create sales/purchases
    * delete inventory

COUNTING STRATEGY (conservative, documented)
--------------------------------------------
Only PRODUCT observations with a non-null product_id are evidence. Results are
camera-scoped: no cross-camera fusion, so two cameras never double-count.

Within one (store, product, camera) and a time window:

1. Drop observations below `min_confidence` (default 0.5). Low-confidence
   detections are IGNORED rather than trusted. Documented rule.

2. Count the surviving observations with the SHARED counting helper in
   `app.services.reconciliation.counting.count_visible` — the exact same rule
   M15 product/shelf intelligence uses (distinct track_ids when tracking is
   available, otherwise max simultaneous per frame with IoU dedup).

Confidence reported is a HEURISTIC: the mean detection confidence of the count's
supporting observations, clearly labelled, NOT a model probability. When there
are no usable observations, confidence is NULL and status becomes REVIEW_REQUIRED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Inventory,
    Observation,
    OBS_PRODUCT,
    Product,
    ReconciliationResult,
    REC_MATCH,
    REC_SURPLUS,
    REC_SHORTAGE,
    REC_REVIEW,
)
from app.services.reconciliation.counting import count_visible

# Default minimum confidence for a PRODUCT observation to count as evidence.
DEFAULT_MIN_CONFIDENCE = 0.5

# IoU threshold: same-frame bboxes overlapping above this are the same instance.
OVERLAP_IOU = 0.5


class ReconciliationService:
    """Compare persisted observations with inventory; persist results only."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def reconcile_product(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        camera_id: Optional[UUID] = None,
        start: datetime,
        end: datetime,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> ReconciliationResult:
        """Reconcile one product (optionally camera-scoped) and persist a result."""
        return self.reconcile_store(
            store_id=store_id,
            start=start,
            end=end,
            min_confidence=min_confidence,
            product_ids=[product_id],
            camera_id=camera_id,
        )[0]

    def reconcile_store(
        self,
        *,
        store_id: UUID,
        start: datetime,
        end: datetime,
        product_ids: Optional[Sequence[UUID]] = None,
        camera_id: Optional[UUID] = None,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> List[ReconciliationResult]:
        """Reconcile products of a store (optionally a subset / camera scope).

        Returns one ReconciliationResult per (product, camera). Each is persisted
        atomically. Inventory is never modified.
        """
        products = self._target_products(store_id, product_ids)
        results: List[ReconciliationResult] = []
        for product in products:
            # Gather camera scope(s): the given camera, or each distinct camera
            # that observed this product (camera-scoped, no fusion).
            cameras = self._camera_scope(camera_id, store_id, product.id, start, end)
            for cam in cameras:
                result = self._reconcile_one(
                    store_id=store_id,
                    product_id=product.id,
                    camera_id=cam,
                    start=start,
                    end=end,
                    min_confidence=min_confidence,
                )
                results.append(result)
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _target_products(
        self, store_id: UUID, product_ids: Optional[Sequence[UUID]]
    ) -> List[Product]:
        stmt = select(Product).where(Product.store_id == store_id)
        if product_ids is not None:
            stmt = stmt.where(Product.id.in_(list(product_ids)))
        return list(self.session.scalars(stmt))

    def _camera_scope(
        self,
        camera_id: Optional[UUID],
        store_id: UUID,
        product_id: UUID,
        start: datetime,
        end: datetime,
    ) -> List[Optional[UUID]]:
        if camera_id is not None:
            return [camera_id]
        # Camera-scoped by design: one result per camera that observed the
        # product, plus a single store-wide (NULL camera) result if there were
        # observations without a camera. No cross-camera fusion.
        base = select(Observation.camera_id).where(
            Observation.observation_type == OBS_PRODUCT,
            Observation.store_id == store_id,
            Observation.product_id == product_id,
            Observation.observed_at >= start,
            Observation.observed_at <= end,
        )
        cams = {c for (c,) in self.session.execute(base).all()}
        return list(sorted(cams, key=lambda x: (x is not None, str(x))))

    def _fetch_observations(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        camera_id: Optional[UUID],
        start: datetime,
        end: datetime,
        min_confidence: float,
    ) -> List[Observation]:
        stmt = (
            select(Observation)
            .where(
                Observation.observation_type == OBS_PRODUCT,
                Observation.store_id == store_id,
                Observation.product_id == product_id,
                Observation.observed_at >= start,
                Observation.observed_at <= end,
                Observation.camera_id.is_(None) if camera_id is None else (
                    Observation.camera_id == camera_id
                ),
            )
        )
        # Apply documented min-confidence filter BEFORE counting.
        if min_confidence > 0.0:
            stmt = stmt.where(
                Observation.confidence.is_(None)
                | (Observation.confidence >= min_confidence)
            )
        return list(self.session.scalars(stmt))

    def _database_quantity(self, store_id: UUID, product_id: UUID) -> int:
        inv = self.session.scalar(
            select(Inventory).where(
                Inventory.store_id == store_id,
                Inventory.product_id == product_id,
            )
        )
        return inv.quantity if inv is not None else 0

    def _count_observed(self, observations: Sequence[Observation]) -> tuple:
        """Return (observed_qty, mean_confidence, per_frame_counts, rule)."""
        observed, mean_conf, per_frame_counts, rule = count_visible(observations)
        return observed, mean_conf, per_frame_counts, rule

    def _reconcile_one(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        camera_id: Optional[UUID],
        start: datetime,
        end: datetime,
        min_confidence: float,
    ) -> ReconciliationResult:
        observations = self._fetch_observations(
            store_id=store_id,
            product_id=product_id,
            camera_id=camera_id,
            start=start,
            end=end,
            min_confidence=min_confidence,
        )
        observed, mean_conf, per_frame_counts, rule = self._count_observed(observations)
        db_qty = self._database_quantity(store_id, product_id)
        difference = observed - db_qty

        # REVIEW_REQUIRED when there is no reliable AI evidence to compare.
        if not observations or (mean_conf is None and observed == 0):
            status = REC_REVIEW
        elif difference == 0:
            status = REC_MATCH
        elif difference > 0:
            status = REC_SURPLUS
        else:
            status = REC_SHORTAGE

        result = ReconciliationResult(
            store_id=store_id,
            product_id=product_id,
            camera_id=camera_id,
            observation_window_start=start,
            observation_window_end=end,
            database_quantity=db_qty,
            ai_observed_quantity=observed,
            difference=difference,
            status=status,
            confidence=mean_conf,  # documented heuristic, NOT a probability
            details={
                "counting_rule": rule,
                "supporting_observations": len(observations),
                "min_confidence_applied": min_confidence,
                "per_frame_instance_counts": (
                    {"frames": len(per_frame_counts), "counts": per_frame_counts}
                    if per_frame_counts
                    else None
                ),
                "confidence_note": (
                    "mean detection confidence of supporting observations; "
                    "a heuristic, not a model probability"
                ),
            },
        )
        self.session.add(result)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(result)
        return result
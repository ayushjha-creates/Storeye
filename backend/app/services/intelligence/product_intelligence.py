"""Product intelligence derived from real Edge AI observations.

Every row is (class OR product, camera)-scoped — cross-camera fusion is
intentionally NOT performed. Rows are grouped by AI class label then mapped to
a product ONLY through the explicit, configurable `products.ai_classes`
declaration; an unmapped class is surfaced as "Unmapped AI class" (mapped=False)
and is never silently tied to a product.

Visible quantity uses the SAME shared counting strategy as reconciliation
(`count_visible`): distinct track_ids when available, else max-simultaneous-per
-frame with IoU dedup. Low-confidence detections are dropped before counting.

AI vs. INVENTORY (informational only):
    `database_quantity` is the recorded inventory row for the product in the
    store (None => no inventory record). `difference` = visible - database and
    `comparison_status` is derived WITHOUT ever mutating inventory:
        MATCH              visible == database (both known)
        POSSIBLE_SHORTAGE  visible <  database
        POSSIBLE_SURPLUS   visible >  database
        NO_INVENTORY       product has no inventory record (nothing to compare)
        NOT_ASSESSED       unmapped class (no product to compare against)
    These are AI-visibility comparisons, never claims about true stock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Camera, Inventory, OBS_PRODUCT, Observation, Product
from app.services.reconciliation.counting import bbox_center, count_visible, point_in_rect

from .shelf_intelligence import ShelfRegion, parse_shelf_regions

# Comparison statuses (informational; never auto-reconciles).
COMP_MATCH = "MATCH"
COMP_SHORTAGE = "POSSIBLE_SHORTAGE"
COMP_SURPLUS = "POSSIBLE_SURPLUS"
COMP_NO_INVENTORY = "NO_INVENTORY"
COMP_NOT_ASSESSED = "NOT_ASSESSED"


@dataclass
class ProductIntelligenceRow:
    """One (AI class, camera) intelligence observation, product when mapped."""

    ai_class: str
    mapped: bool
    product_id: Optional[UUID]
    product_name: Optional[str]
    sku: Optional[str]
    camera_id: Optional[UUID]
    camera_name: Optional[str]
    shelf_code: Optional[str]  # derived region code, or None ("Shelf: Unknown")
    visible_count: int
    confidence: Optional[float]
    counting_rule: str
    latest_observed_at: Optional[datetime] = None
    database_quantity: Optional[int] = None
    difference: Optional[int] = None
    comparison_status: str = COMP_NOT_ASSESSED
    message: Optional[str] = None


class ProductIntelligenceService:
    """Derive product intelligence from observed product detections."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def products(
        self,
        *,
        store_id: UUID,
        camera_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        class_name: Optional[str] = None,
        min_confidence: float = 0.5,
        hours: int = 24,
    ) -> List[ProductIntelligenceRow]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=min(max(int(hours), 1), 24 * 7))

        cameras = self._cameras(store_id, camera_id)
        camera_ids = [c.id for c in cameras]
        if not camera_ids:
            return []

        class_map = self._class_to_product(store_id)

        # Resolve a product filter into its declared AI classes (explicit only).
        class_filter: Optional[List[str]] = None
        if product_id is not None:
            class_filter = [
                cls for cls, p in class_map.items() if p.id == product_id
            ]
            if not class_filter:
                return []  # product exists but declares no AI classes -> no data

        observations = self._product_observations(
            store_id=store_id,
            camera_ids=camera_ids,
            start=start,
            end=end,
            min_confidence=min_confidence,
            class_filter=class_filter,
            class_name=class_name,
        )
        if not observations:
            return []

        by_camera_id = {c.id: c for c in cameras}
        regions_by_camera = {c.id: parse_shelf_regions(c) for c in cameras if c.config}
        inventory = self._inventory_lookup(store_id, {p.id for p in class_map.values()})

        by_key: Dict[Tuple[str, UUID], List[Observation]] = {}
        for o in observations:
            cls = self._class_of(o)
            by_key.setdefault((cls, o.camera_id), []).append(o)

        rows: List[ProductIntelligenceRow] = []
        for (cls, cam_id), group in by_key.items():
            visible, conf, _, rule = count_visible(group)
            prod = class_map.get(cls)
            shelf_code = self._best_region_code(group, regions_by_camera.get(cam_id, []))
            row = ProductIntelligenceRow(
                ai_class=cls,
                mapped=prod is not None,
                product_id=prod.id if prod else None,
                product_name=prod.name if prod else None,
                sku=prod.sku if prod else None,
                camera_id=cam_id,
                camera_name=by_camera_id.get(cam_id).name if cam_id in by_camera_id else None,
                shelf_code=shelf_code,
                visible_count=visible,
                confidence=conf,
                counting_rule=rule,
                latest_observed_at=max(
                    (o.observed_at for o in group if o.observed_at), default=None
                ),
            )
            if prod is not None:
                db_qty = inventory.get(prod.id)
                row.database_quantity = db_qty
                if db_qty is None:
                    row.comparison_status = COMP_NO_INVENTORY
                    row.message = "No inventory record for this product yet."
                else:
                    row.difference = visible - db_qty
                    if row.difference == 0:
                        row.comparison_status = COMP_MATCH
                    elif row.difference < 0:
                        row.comparison_status = COMP_SHORTAGE
                    else:
                        row.comparison_status = COMP_SURPLUS
            else:
                row.comparison_status = COMP_NOT_ASSESSED
                row.message = "Unmapped AI class — assign Product.ai_classes to tie it to a product."
            rows.append(row)

        rows.sort(key=lambda r: (-r.visible_count, r.ai_class.lower()))
        return rows

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _cameras(self, store_id: UUID, camera_id: Optional[UUID]) -> List[Camera]:
        stmt = select(Camera).where(Camera.store_id == store_id)
        if camera_id is not None:
            stmt = stmt.where(Camera.id == camera_id)
        return list(self.session.scalars(stmt))

    def _class_to_product(self, store_id: UUID) -> Dict[str, Product]:
        stmt = (
            select(Product)
            .where(Product.store_id == store_id, Product.ai_classes.is_not(None))
            .order_by(Product.sku)
        )
        mapping: Dict[str, Product] = {}
        for p in self.session.scalars(stmt):
            for cls in p.ai_classes or []:
                if isinstance(cls, str) and cls not in mapping:
                    mapping[cls] = p
        return mapping

    def _inventory_lookup(
        self, store_id: UUID, product_ids: set
    ) -> Dict[UUID, int]:
        if not product_ids:
            return {}
        stmt = select(Inventory.product_id, Inventory.quantity).where(
            Inventory.store_id == store_id,
            Inventory.product_id.in_([p for p in product_ids if p]),
        )
        return {pid: qty for pid, qty in self.session.execute(stmt)}

    def _product_observations(
        self,
        *,
        store_id: UUID,
        camera_ids: List[UUID],
        start: datetime,
        end: datetime,
        min_confidence: float,
        class_filter: Optional[List[str]],
        class_name: Optional[str],
    ) -> List[Observation]:
        conds = [
            Observation.observation_type == OBS_PRODUCT,
            Observation.store_id == store_id,
            Observation.camera_id.in_(camera_ids),
            Observation.observed_at >= start,
            Observation.observed_at <= end,
        ]
        if min_confidence > 0.0:
            # Low-confidence detections are IGNORED, never trusted.
            conds.append(Observation.confidence.is_not(None))
            conds.append(Observation.confidence >= min_confidence)
        if class_filter is not None and class_filter:
            conds.append(Observation.details["class_name"].astext.in_(class_filter))
        elif class_name is not None:
            conds.append(Observation.details["class_name"].astext == class_name)
        return list(
            self.session.scalars(
                select(Observation).where(*conds).order_by(Observation.observed_at)
            )
        )

    @staticmethod
    def _class_of(obs: Observation) -> str:
        cls = (obs.details or {}).get("class_name") if obs.details else None
        return cls if isinstance(cls, str) and cls else "unknown"

    @staticmethod
    def _best_region_code(obs: List[Observation], regions: List[ShelfRegion]) -> Optional[str]:
        """Majority association: the first region (config order) containing the
        greatest number of bounding-box centers. None when no center matches."""
        if not regions:
            return None
        counts: Dict[str, int] = {}
        for o in obs:
            if not isinstance(o.bbox, (list, tuple)) or len(o.bbox) < 4:
                continue
            cx, cy = bbox_center([float(v) for v in o.bbox])
            for r in regions:
                if point_in_rect(cx, cy, r.bbox):
                    counts[r.code] = counts.get(r.code, 0) + 1
                    break
        if not counts:
            return None
        best = max(counts.items(), key=lambda kv: (kv[1], -regions_index(regions, kv[0])))
        return best[0]


def regions_index(regions: List[ShelfRegion], code: str) -> int:
    for r in regions:
        if r.code == code:
            return r.index
    return 0
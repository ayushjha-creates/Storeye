"""Shelf intelligence derived from real Edge AI observations.

Shelf "regions" are configured per camera in `camera.config.shelf_regions` —
a list of {code, label?, bbox:[x1,y1,x2,y2]} entries. Nothing is persisted at
inference time; every result here is DERIVED from observations on read.

GEOMETRIC PRODUCT->SHELF ASSOCIATION (deterministic, documented rule):
    A product observation's bounding-box CENTER
        (cx, cy) = ((x1+x2)/2, (y1+y2)/2)
    belongs to the FIRST configured region (in config order) whose
    [x1, y1, x2, y2] contains the center (inclusive). If no region contains
    the center, the product is "Shelf: Unknown". This is a simple, explicit
    heuristic — it does NOT claim perfect physical shelf association.

VISIBLE OCCUPANCY (clearly labelled an estimate):
    occupancy = clamp( sum( area(bbox_x_region) ) / area(region) )
    using the observations associated to the region. Always presented as
    "AI-estimated visible occupancy", never as exact stock. When there is no
    AI data it is "Occupancy unavailable" (None).
    When observations span enough wall-clock minute-buckets, the MEDIAN of the
    per-bucket occupancies is used (temporal smoothing) and reported via
    `occupancy_method="median_60s"`; otherwise the raw value is reported
    (`occupancy_method="raw"`). Smoothing never invents data.

SHELF STATES:
    UNKNOWN          no product observations for the camera in the window
                     (camera offline / pipeline off / window empty)
    EMPTY_VISIBLE    AI sees no visible product in this region -> fill ASAP
    LOW_VISIBLE      visible occupancy at/below LOW_OCCUPANCY_FRACTION (half)
                     -> "about to get empty", refill soon
    NORMAL_VISIBLE   otherwise
    These are NEVER called "out of stock" — the AI only knows what is visible.
    `refill_recommended` is True for EMPTY_VISIBLE and LOW_VISIBLE so callers
    (alerts, UI) do not each re-derive the threshold.

MISPLACEMENT FOUNDATION:
    A detected product is a POSSIBLE_MISPLACEMENT candidate only when the
    shelf has an EXPLICIT expectation (an active PlanogramItem mapping that
    shelf -> product) AND the detected product is MAPPED (Product.ai_classes)
    AND that product is not in the shelf's expectation. Products without a
    mapping are never flagged (we can't tell what they are). This is an AI
    inference foundation only — it never alters inventory or the planogram.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Camera,
    Observation,
    OBS_PRODUCT,
    Planogram,
    PlanogramItem,
    Product,
    Shelf,
    Zone,
)
from app.services.reconciliation.counting import (
    bbox_center,
    count_visible,
    point_in_rect,
    rect_area,
    rect_intersection_area,
)

# States — visible-only semantics, never "out of stock".
SHELF_STATE_UNKNOWN = "UNKNOWN"
SHELF_STATE_EMPTY = "EMPTY_VISIBLE"
SHELF_STATE_LOW = "LOW_VISIBLE"
SHELF_STATE_NORMAL = "NORMAL_VISIBLE"

# At/below this visible-occupancy fraction a populated shelf is labelled LOW
# ("half full or less" -> refill soon). EMPTY_VISIBLE is handled separately.
LOW_OCCUPANCY_FRACTION = 0.5

# Temporal smoothing (M27 Phase 10-11). Occupancy is computed per time bucket
# (observations grouped by wall-clock minute) and reduced with the MEDIAN, so a
# one-off detection spike/crossing does not flip the shelf state. Falls back to
# the raw whole-window value when there are too few buckets to smooth honestly.
SHELF_SMOOTHING_BUCKET_SECONDS = 60.0
SHELF_SMOOTHING_MIN_BUCKETS = 3


@dataclass
class ShelfRegion:
    """A configured pixel region of a camera (camera.config.shelf_regions)."""

    code: str
    label: Optional[str]
    bbox: List[float]  # [x1, y1, x2, y2]
    index: int


@dataclass
class ShelfVisibleProduct:
    """One class/product visible within a shelf region (AI-derived)."""

    ai_class: str
    product_id: Optional[UUID]
    product_name: Optional[str]
    sku: Optional[str]
    visible_count: int
    confidence: Optional[float]
    counting_rule: str
    # Misplacement foundation fields.
    expected_on_shelf: Optional[bool]  # None => no expectation / can't assess
    possible_misplacement: bool = False


@dataclass
class ShelfIntelligenceRow:
    """One (camera, configured shelf region) intelligence result."""

    shelf_code: str
    region_label: Optional[str]
    shelf_id: Optional[UUID]
    zone_id: Optional[UUID]
    zone_name: Optional[str]
    camera_id: Optional[UUID]
    camera_name: Optional[str]
    bbox: List[float]
    detection_status: str
    estimated_visible_occupancy: Optional[float]  # None => "Occupancy unavailable"
    occupied_pct: Optional[float] = None
    visible_products: List[ShelfVisibleProduct] = field(default_factory=list)
    latest_observed_at: Optional[datetime] = None
    mean_confidence: Optional[float] = None
    last_analysis_message: Optional[str] = None
    # How the visible occupancy was derived: "raw" (whole window) or
    # "median_60s" (temporal smoothing) + the number of time buckets used.
    occupancy_method: Optional[str] = None
    occupancy_samples: Optional[int] = None
    # True when AI evidence says this shelf should be refilled (empty or half
    # full or less). Never True for UNKNOWN (no evidence).
    refill_recommended: bool = False


def parse_shelf_regions(camera: Camera) -> List[ShelfRegion]:
    """Read + validate `camera.config.shelf_regions`. Invalid entries are
    skipped, never used to build a tie to a shelf. Deterministic order."""
    raw = (camera.config or {}).get("shelf_regions")
    if not isinstance(raw, list):
        return []
    regions: List[ShelfRegion] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        bbox = entry.get("bbox")
        if not isinstance(code, str) or not code.strip():
            continue
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            continue
        try:
            bx = [float(v) for v in bbox]
        except (TypeError, ValueError):
            continue
        if rect_area(bx) <= 0:
            continue
        regions.append(
            ShelfRegion(
                code=code.strip(),
                label=entry.get("label") if isinstance(entry.get("label"), str) else None,
                bbox=bx,
                index=idx,
            )
        )
    return regions


class ShelfIntelligenceService:
    """Derive shelf intelligence from observed product detections."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def shelves(
        self,
        *,
        store_id: UUID,
        camera_id: Optional[UUID] = None,
        min_confidence: float = 0.5,
        hours: int = 24,
    ) -> List[ShelfIntelligenceRow]:
        """Shelf results for a store (optionally a single camera). Read-only."""
        cameras = self._cameras(store_id, camera_id)
        if not cameras:
            return []
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=min(max(int(hours), 1), 24 * 7))

        rows: List[ShelfIntelligenceRow] = []
        for cam in cameras:
            regions = parse_shelf_regions(cam)
            if not regions:
                continue
            obs = self._product_observations(
                store_id=store_id, camera_id=cam.id, start=start, end=end,
                min_confidence=min_confidence,
            )
            camera_has_ai_data = bool(obs)
            shelf_map = self._shelf_lookup(store_id, [r.code for r in regions])
            expectations = self._shelf_expectations(store_id)
            for region in regions:
                rows.append(
                    self._shelf_row(
                        cam=cam,
                        region=region,
                        observations=obs,
                        camera_has_ai_data=camera_has_ai_data,
                        shelf_map=shelf_map,
                        expectations=expectations,
                    )
                )
        return rows

    def shelf_products(
        self,
        *,
        store_id: UUID,
        camera_id: Optional[UUID] = None,
        region_code: Optional[str] = None,
        min_confidence: float = 0.5,
        hours: int = 24,
    ) -> List[ShelfVisibleProduct]:
        rows = self.shelves(
            store_id=store_id,
            camera_id=camera_id,
            min_confidence=min_confidence,
            hours=hours,
        )
        out: List[ShelfVisibleProduct] = []
        for r in rows:
            if region_code is not None and r.shelf_code != region_code:
                continue
            out.extend(r.visible_products)
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _cameras(self, store_id: UUID, camera_id: Optional[UUID]) -> List[Camera]:
        stmt = select(Camera).where(Camera.store_id == store_id)
        if camera_id is not None:
            stmt = stmt.where(Camera.id == camera_id)
        return list(self.session.scalars(stmt))

    def _product_observations(
        self,
        *,
        store_id: UUID,
        camera_id: UUID,
        start: datetime,
        end: datetime,
        min_confidence: float,
    ) -> List[Observation]:
        conds = [
            Observation.observation_type == OBS_PRODUCT,
            Observation.store_id == store_id,
            Observation.camera_id == camera_id,
            Observation.observed_at >= start,
            Observation.observed_at <= end,
        ]
        if min_confidence > 0.0:
            # Low-confidence detections are IGNORED, never trusted.
            conds.append(Observation.confidence.is_not(None))
            conds.append(Observation.confidence >= min_confidence)
        return list(
            self.session.scalars(
                select(Observation).where(*conds).order_by(Observation.observed_at)
            )
        )

    def _shelf_lookup(
        self, store_id: UUID, codes: List[str]
    ) -> Dict[str, Tuple[Shelf, Optional[Zone]]]:
        if not codes:
            return {}
        # Deterministic: duplicate shelf codes resolve to the lowest-id shelf
        # (ORDER BY without a tie-breaker let the row order vary by plan).
        stmt = (
            select(Shelf, Zone)
            .outerjoin(Zone, Zone.id == Shelf.zone_id)
            .where(Shelf.store_id == store_id, Shelf.code.in_(codes))
            .order_by(Shelf.code, Shelf.id)
        )
        result: Dict[str, Tuple[Shelf, Optional[Zone]]] = {}
        for shelf, zone in self.session.execute(stmt):
            if shelf.code not in result:
                result[shelf.code] = (shelf, zone)
        return result

    def _shelf_expectations(self, store_id: UUID) -> Dict[UUID, set]:
        """Active planogram shelf_id -> {expected product ids}. Empty for
        shelves with no active planogram (no expectation to compare against)."""
        outer = (
            select(Planogram.id)
            .where(Planogram.store_id == store_id, Planogram.is_active.is_(True))
        )
        active_ids = list(self.session.scalars(outer))
        if not active_ids:
            return {}
        stmt = select(PlanogramItem.shelf_id, PlanogramItem.product_id).where(
            PlanogramItem.planogram_id.in_(active_ids),
            PlanogramItem.expected_facings > 0,
        )
        expectations: Dict[UUID, set] = {}
        for shelf_id, product_id in self.session.execute(stmt):
            expectations.setdefault(shelf_id, set()).add(product_id)
        return expectations

    def _product_lookup(self, store_id: UUID) -> Dict[str, Product]:
        """class_name -> Product mapping from the EXPLICIT ai_classes config."""
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

    def _shelf_row(
        self,
        *,
        cam: Camera,
        region: ShelfRegion,
        observations: List[Observation],
        camera_has_ai_data: bool,
        shelf_map: Dict[str, Tuple[Shelf, Optional[Zone]]],
        expectations: Dict[UUID, set],
    ) -> ShelfIntelligenceRow:
        associated = [
            o for o in observations
            if self._in_region(o, region.bbox)
        ]
        shelf, zone = shelf_map.get(region.code, (None, None))

        confidence: Optional[float] = None
        latest: Optional[datetime] = None
        confs: List[float] = []
        for o in associated:
            if o.observed_at and (latest is None or o.observed_at > latest):
                latest = o.observed_at
            if o.confidence is not None:
                confs.append(o.confidence)
        if confs:
            confidence = round(sum(confs) / len(confs), 4)

        row = ShelfIntelligenceRow(
            shelf_code=region.code,
            region_label=region.label,
            shelf_id=shelf.id if shelf else None,
            zone_id=zone.id if zone else None,
            zone_name=zone.name if zone else None,
            camera_id=cam.id,
            camera_name=cam.name,
            bbox=region.bbox,
            detection_status=SHELF_STATE_UNKNOWN,
            estimated_visible_occupancy=None,
            latest_observed_at=latest,
            mean_confidence=confidence,
        )

        if not camera_has_ai_data:
            row.last_analysis_message = "No AI data in window (camera offline or pipeline off)."
            return row

        # Occupancy estimate (clearly labelled as AI-estimated), temporally
        # smoothed with a median across wall-clock buckets where possible.
        occupancy, method, samples = self._smoothed_occupancy(associated, region.bbox)
        row.estimated_visible_occupancy = round(occupancy, 4)
        row.occupied_pct = round(row.estimated_visible_occupancy * 100, 1)
        row.occupancy_method = method
        row.occupancy_samples = samples

        if not associated:
            row.detection_status = SHELF_STATE_EMPTY
            row.refill_recommended = True
            row.last_analysis_message = (
                "AI sees no visible product in this region "
                "(could be hidden/behind stock) — refill as soon as possible."
            )
            return row

        product_map = self._product_lookup(cam.store_id)
        exp = expectations.get(shelf.id) if shelf else None

        by_class: Dict[str, List[Observation]] = {}
        for o in associated:
            cls = (o.details or {}).get("class_name") if o.details else None
            cls = cls if isinstance(cls, str) and cls else "unknown"
            by_class.setdefault(cls, []).append(o)

        for cls, group in by_class.items():
            visible, conf, _, rule = count_visible(group)
            prod = product_map.get(cls)
            expected: Optional[bool] = None
            misplaced = False
            if prod is not None and exp is not None:
                expected = prod.id in exp
                misplaced = not expected
            row.visible_products.append(
                ShelfVisibleProduct(
                    ai_class=cls,
                    product_id=prod.id if prod else None,
                    product_name=prod.name if prod else None,
                    sku=prod.sku if prod else None,
                    visible_count=visible,
                    confidence=conf,
                    counting_rule=rule,
                    expected_on_shelf=expected,
                    possible_misplacement=misplaced,
                )
            )

        if row.estimated_visible_occupancy <= LOW_OCCUPANCY_FRACTION:
            row.detection_status = SHELF_STATE_LOW
            row.refill_recommended = True
        else:
            row.detection_status = SHELF_STATE_NORMAL
        row.last_analysis_message = (
            "AI-estimated visible occupancy from associated product detections "
            "(informational; not stock)."
        )
        return row

    @staticmethod
    def _smoothed_occupancy(
        observations: List[Observation], region_bbox: List[float]
    ) -> Tuple[float, str, int]:
        """Return (occupancy, method, samples).

        Raw occupancy = Σ intersection-area / region-area over the window.
        When observations span >= SHELF_SMOOTHING_MIN_BUCKETS wall-clock
        minute-buckets, return the MEDIAN of the per-bucket occupancies instead
        (robust to a single spike). Otherwise fall back to raw — never invent
        smoothing from too little data.
        """
        area = rect_area(region_bbox)
        if area <= 0:
            return 0.0, "raw", 0

        def _bucket_occupancy(obs_group: List[Observation]) -> float:
            occupied = sum(
                rect_intersection_area(list(o.bbox), region_bbox)
                for o in obs_group
                if isinstance(o.bbox, (list, tuple))
            )
            return min(1.0, occupied / area)

        buckets: Dict[int, List[Observation]] = {}
        untimed: List[Observation] = []
        for o in observations:
            if o.observed_at is None:
                untimed.append(o)
                continue
            key = int(o.observed_at.timestamp() // SHELF_SMOOTHING_BUCKET_SECONDS)
            buckets.setdefault(key, []).append(o)

        if len(buckets) >= SHELF_SMOOTHING_MIN_BUCKETS:
            per_bucket = [_bucket_occupancy(group) for group in buckets.values()]
            return float(median(per_bucket)), "median_60s", len(per_bucket)

        return _bucket_occupancy(observations), "raw", len(buckets)

    @staticmethod
    def _in_region(obs: Observation, region: List[float]) -> bool:
        if not isinstance(obs.bbox, (list, tuple)) or len(obs.bbox) < 4:
            return False
        cx, cy = bbox_center([float(v) for v in obs.bbox])
        return point_in_rect(cx, cy, region)
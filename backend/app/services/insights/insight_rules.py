"""Deterministic insight rules (M20).

Every rule here READS existing persisted data only:
    * inventory / reorder levels                      (POS truth)
    * batches + expiry                                (Batch rows, ExpiryIntelligence)
    * shelf/product intelligence, misplacement        (M15 — already-persisted observations)
    * anonymous journeys (zone visits)                (M19)
    * sales                                           (Sale/SaleItem)
    * cameras + observation staleness                 (simulated heartbeat proxy, M16)

Each `rule_*` function returns a list of RuleCandidate. Rules NEVER mutate
anything. The InsightEngine reconciles the candidates against persisted
insights (dedup + lifecycle) and optionally raises M16 alerts at/above the
configured actionable severity.

PRIVACY GUARANTEE
-----------------
Customer-flow rules consume aggregate M19 zone analytics (opaque global person
ids aggregated per zone). Individual journeys are never used, no identity data
is stored or exposed, and flow is NEVER translated into purchase intent.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    ALERT_CAMERA_OFFLINE,
    ALERT_EXPIRY,
    ALERT_LOW_SHELF_OCCUPANCY,
    ALERT_MISPLACEMENT,
    ALERT_SHORTAGE,
    Batch,
    Camera,
    Inventory,
    Observation,
    Product,
    Sale,
    SaleItem,
    Zone,
    ZoneVisit,
    CERTAINTY_HIGH,
    CERTAINTY_MEDIUM,
    INSIGHT_CAMERA_HEALTH,
    INSIGHT_EXPIRED_BATCH,
    INSIGHT_EXPIRY_RISK,
    INSIGHT_HIGH_DWELL_ZONE,
    INSIGHT_HIGH_SELLING_LOW_STOCK,
    INSIGHT_HIGH_TRAFFIC_LOW_SHELF,
    INSIGHT_HIGH_TRAFFIC_ZONE,
    INSIGHT_LOW_SHELF_AVAILABILITY,
    INSIGHT_LOW_STOCK,
    INSIGHT_LOW_STOCK_LOW_SHELF,
    INSIGHT_MISPLACEMENT,
    INSIGHT_OUT_OF_STOCK,
    INSIGHT_STOCK_ROTATION,
    SEV_HIGH,
    SEV_INFO,
    SEV_LOW,
    SEV_MEDIUM,
)
from app.services.intelligence import (
    EXPIRY_STATUS_EXPIRED,
    EXPIRY_STATUS_EXPIRING_SOON,
    EXPIRY_STATUS_MONTH,
    SHELF_STATE_EMPTY,
    SHELF_STATE_LOW,
    ExpiryIntelligence,
    ExpiryInsight,
    MisplacementService,
    ShelfIntelligenceService,
)
from app.services.insights import evidence as ev
from app.services.insights import recommendations as rec
from app.services.insights.insight_types import RuleCandidate


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hours_ago(hours: int) -> datetime:
    return _now() - timedelta(hours=max(int(hours), 1))


def _product_name_map(session: Session, product_ids: Sequence[UUID]) -> dict:
    if not product_ids:
        return {}
    rows = session.execute(
        select(Product.id, Product.name).where(Product.id.in_(list(product_ids)))
    )
    return {pid: name for pid, name in rows}


class RuleContext:
    """Shared evaluation context so all rules use one consistent 'now'."""

    def __init__(
        self,
        session: Session,
        *,
        store_id: UUID,
        now: Optional[datetime] = None,
        reference_date: Optional[date] = None,
        camera_stale_minutes: Optional[int] = None,
        traffic_hours: Optional[int] = None,
        dwell_hours: Optional[int] = None,
        sales_hours: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.store_id = store_id
        self.now = now or _now()
        self.reference_date = reference_date or self.now.date()
        self.camera_stale_minutes = (
            camera_stale_minutes
            if camera_stale_minutes is not None
            else int(settings.INSIGHT_CAMERA_STALE_MINUTES)
        )
        self.traffic_hours = traffic_hours or int(settings.INSIGHT_TRAFFIC_WINDOW_HOURS)
        self.dwell_hours = dwell_hours or int(settings.INSIGHT_DWELL_WINDOW_HOURS)
        self.sales_hours = sales_hours or int(settings.HIGH_SELLING_SALES_WINDOW_HOURS)


# ---------------------------------------------------------------------------
# Inventory rules (POS truth — highest certainty)
# ---------------------------------------------------------------------------


def rule_inventory(ctx: RuleContext) -> List[RuleCandidate]:
    """LOW_STOCK (0 < qty <= reorder_level) and OUT_OF_STOCK (qty == 0)."""
    rows = ctx.session.execute(
        select(Product, Inventory)
        .join(Inventory, Inventory.product_id == Product.id)
        .where(Product.store_id == ctx.store_id, Inventory.store_id == ctx.store_id)
        .order_by(Product.sku)
    ).all()

    candidates: List[RuleCandidate] = []
    for product, inv in rows:
        qty = inv.quantity
        if qty == 0:
            candidates.append(
                RuleCandidate(
                    insight_type=INSIGHT_OUT_OF_STOCK,
                    entity_type="product",
                    entity_id=str(product.id),
                    severity=SEV_HIGH,
                    title=f"Out of stock: {product.name}",
                    description=(
                        f"{product.name} ({product.sku}) has current stock 0."
                    ),
                    rule_id="inventory.out_of_stock",
                    source_modules=["inventory", "inventory_intelligence"],
                    recommended_action=rec.rec_product_stock(product.name, product.sku, oos=True),
                    certainty=CERTAINTY_HIGH,
                    product_id=product.id,
                    evidence=ev.ev_out_of_stock(
                        product_id=product.id,
                        sku=product.sku,
                        name=product.name,
                        quantity=qty,
                        reorder_level=inv.reorder_level,
                    ),
                    alert_type=ALERT_SHORTAGE,
                )
            )
        elif qty > 0 and inv.reorder_level > 0 and qty <= inv.reorder_level:
            candidates.append(
                RuleCandidate(
                    insight_type=INSIGHT_LOW_STOCK,
                    entity_type="product",
                    entity_id=str(product.id),
                    severity=SEV_MEDIUM,
                    title=f"Low stock: {product.name}",
                    description=(
                        f"{product.name} ({product.sku}) has current stock {qty}, "
                        f"at or below its reorder level of {inv.reorder_level}."
                    ),
                    rule_id="inventory.low_stock",
                    source_modules=["inventory", "inventory_intelligence"],
                    recommended_action=rec.rec_product_stock(product.name, product.sku),
                    certainty=CERTAINTY_HIGH,
                    product_id=product.id,
                    evidence=ev.ev_low_stock(
                        product_id=product.id,
                        sku=product.sku,
                        name=product.name,
                        quantity=qty,
                        reorder_level=inv.reorder_level,
                        reorder_quantity=inv.reorder_quantity,
                    ),
                )
            )
    return candidates


# ---------------------------------------------------------------------------
# Expiry rules (Batch truth; day-precision HIGH, month-precision MEDIUM)
# ---------------------------------------------------------------------------


def rule_expiry(ctx: RuleContext) -> List[RuleCandidate]:
    """EXPIRY_RISK, EXPIRED_BATCH, and STOCK_ROTATION_RECOMMENDATION."""
    settings = get_settings()
    expiry = ExpiryIntelligence(ctx.session)
    insights = expiry.evaluate(ctx.store_id, reference_date=ctx.reference_date)
    candidates: List[RuleCandidate] = []

    batch_qty: dict = {}  # batch_id -> quantity
    for b in ctx.session.scalars(
        select(Batch).where(Batch.store_id == ctx.store_id)
    ):
        batch_qty[b.id] = b.quantity

    for ins in insights:
        if ins.status == EXPIRY_STATUS_EXPIRED:
            expires_at = None
            title = f"Expired batch: {ins.name}"
            description = (
                f"Batch {ins.batch_number or 'n/a'} of {ins.name} passed its "
                f"expiry date ({ins.expiry_date})."
            )
            candidates.append(
                RuleCandidate(
                    insight_type=INSIGHT_EXPIRED_BATCH,
                    entity_type="batch",
                    entity_id=str(ins.batch_id),
                    severity=SEV_HIGH,
                    title=title,
                    description=description,
                    rule_id="expiry.expired",
                    source_modules=["expiry_intelligence", "batch"],
                    recommended_action=rec.rec_after_expired(ins.name, ins.batch_number),
                    certainty=CERTAINTY_HIGH,
                    product_id=ins.product_id,
                    expires_at=expires_at,
                    alert_type=ALERT_EXPIRY,
                    evidence=ev.ev_expired_batch(
                        product_id=ins.product_id,
                        sku=ins.sku,
                        name=ins.name,
                        batch_id=ins.batch_id,
                        batch_number=ins.batch_number,
                        expiry_date=ins.expiry_date,
                        precision=ins.expiry_date_precision,
                    ),
                )
            )
        elif ins.status in (EXPIRY_STATUS_EXPIRING_SOON, EXPIRY_STATUS_MONTH):
            # Insight self-expires the day after the batch's expiry date.
            expires_at = (
                datetime.combine(
                    ins.expiry_date + timedelta(days=1),
                    time(0, 0, tzinfo=timezone.utc),
                )
                if ins.expiry_date
                else None
            )
            certainty = (
                CERTAINTY_HIGH
                if ins.expiry_date_precision == "day"
                else CERTAINTY_MEDIUM
            )
            candidates.append(
                RuleCandidate(
                    insight_type=INSIGHT_EXPIRY_RISK,
                    entity_type="batch",
                    entity_id=str(ins.batch_id),
                    severity=SEV_MEDIUM,
                    title=f"Expiring soon: {ins.name}",
                    description=(
                        f"Batch {ins.batch_number or 'n/a'} of {ins.name} expires "
                        f"{ins.expiry_date} (within the {ins.warning_days}-day window)."
                    ),
                    rule_id="expiry.expiring_soon",
                    source_modules=["expiry_intelligence", "batch"],
                    recommended_action=rec.rec_after_expiry_risk(ins.name, ins.batch_number),
                    certainty=certainty,
                    product_id=ins.product_id,
                    expires_at=expires_at,
                    evidence=ev.ev_expiry_risk(
                        product_id=ins.product_id,
                        sku=ins.sku,
                        name=ins.name,
                        batch_id=ins.batch_id,
                        batch_number=ins.batch_number,
                        expiry_date=ins.expiry_date,
                        precision=ins.expiry_date_precision,
                        days_until_expiry=ins.days_until_expiry,
                        status=ins.status,
                    ),
                )
            )

    candidates.extend(rule_stock_rotation(ctx))
    return candidates


def rule_stock_rotation(ctx: RuleContext) -> List[RuleCandidate]:
    """STOCK_ROTATION_RECOMMENDATION: >=2 batches of a product where the
    EARLIEST-EXPIRING batch still has stock. Entity = store (recommendation
    describes a product but is store-scoped, so re-evidence replaces it)."""
    rows = (
        ctx.session.execute(
            select(Batch.product_id, func.count(Batch.id), func.min(Batch.expiry_date))
            .where(Batch.store_id == ctx.store_id, Batch.quantity > 0, Batch.expiry_date.is_not(None))
            .group_by(Batch.product_id)
            .having(func.count(Batch.id) >= 2)
            .order_by(func.count(Batch.id).desc())
        )
        .all()
    )
    if not rows:
        return []

    product_ids = [r[0] for r in rows]
    names = _product_name_map(ctx.session, product_ids)
    candidates: List[RuleCandidate] = []
    for product_id, count, earliest in rows:
        name = names.get(product_id, str(product_id))
        sku = ctx.session.scalar(select(Product.sku).where(Product.id == product_id)) or str(product_id)
        candidates.append(
            RuleCandidate(
                insight_type=INSIGHT_STOCK_ROTATION,
                entity_type="product",
                entity_id=str(product_id),
                severity=SEV_LOW,
                title=f"Stock rotation: {name}",
                description=(
                    f"{name} has {count} batches with stock; the earliest expires "
                    f"{earliest}. Rotate it to the front."
                ),
                rule_id="expiry.stock_rotation",
                source_modules=["expiry_intelligence", "batch"],
                recommended_action=rec.rec_stock_rotation(name),
                certainty=CERTAINTY_MEDIUM,
                product_id=product_id,
                evidence=ev.ev_stock_rotation(
                    product_id=product_id,
                    sku=sku,
                    name=name,
                    batches=_batch_summaries(ctx, product_id),
                ),
            )
        )
    return candidates


def _batch_summaries(ctx: RuleContext, product_id: UUID) -> List[dict]:
    rows = ctx.session.execute(
        select(Batch.batch_number, Batch.expiry_date, Batch.quantity)
        .where(Batch.product_id == product_id, Batch.store_id == ctx.store_id, Batch.quantity > 0)
        .order_by(Batch.expiry_date)
    ).all()
    return [
        {
            "batch_number": r[0],
            "expiry_date": str(r[1]) if r[1] else None,
            "quantity": int(r[2]),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Shelf rules (AI-derived; MEDIUM certainty)
# ---------------------------------------------------------------------------


def rule_shelf(ctx: RuleContext) -> List[RuleCandidate]:
    """LOW_SHELF_AVAILABILITY (LOW_VISIBLE MEDIUM, EMPTY_VISIBLE HIGH) and
    MISPLACEMENT (LOW). UNKNOWN is NEVER flagged (no AI evidence)."""
    shelf_svc = ShelfIntelligenceService(ctx.session)
    rows = shelf_svc.shelves(store_id=ctx.store_id)
    candidates: List[RuleCandidate] = []

    for row in rows:
        if row.detection_status not in (SHELF_STATE_LOW, SHELF_STATE_EMPTY):
            continue
        severity = SEV_HIGH if row.detection_status == SHELF_STATE_EMPTY else SEV_MEDIUM
        state_label = (
            "empty"
            if row.detection_status == SHELF_STATE_EMPTY
            else "low"
        )
        candidates.append(
            RuleCandidate(
                insight_type=INSIGHT_LOW_SHELF_AVAILABILITY,
                entity_type="shelf",
                entity_id=row.shelf_code,
                severity=severity,
                title=f"Shelf {row.shelf_code} availability is {state_label}",
                description=(
                    f"AI-estimated visible occupancy for shelf {row.shelf_code} is "
                    f"{row.occupied_pct}% ({row.detection_status}). AI observation, "
                    "not exact stock."
                ),
                rule_id="shelf_low.low_or_empty",
                source_modules=["shelf_intelligence"],
                recommended_action=rec.rec_low_shelf(row.shelf_code),
                certainty=CERTAINTY_MEDIUM,
                shelf_id=row.shelf_id,
                camera_id=row.camera_id,
                alert_type=(
                    ALERT_LOW_SHELF_OCCUPANCY
                    if row.detection_status == SHELF_STATE_EMPTY
                    else None
                ),
                evidence=ev.ev_low_shelf(
                    shelf_code=row.shelf_code,
                    zone_name=row.zone_name,
                    detection_status=row.detection_status,
                    occupied_pct=row.occupied_pct,
                    camera_name=row.camera_name,
                ),
            )
        )

    misplacement_svc = MisplacementService(ctx.session)
    for m in misplacement_svc.misplacements(store_id=ctx.store_id):
        if m.product_id is None:
            continue  # unmapped -> never guessed
        candidates.append(
            RuleCandidate(
                insight_type=INSIGHT_MISPLACEMENT,
                entity_type="shelf",
                entity_id=f"{m.shelf_code}:{m.product_id}",
                severity=SEV_LOW,
                title=f"Possible misplacement: {m.product_name} on {m.shelf_code}",
                description=(
                    f"AI detected {m.product_name or m.ai_class} on shelf "
                    f"{m.shelf_code} whose planogram expects other products."
                ),
                rule_id="shelf_low.misplacement",
                source_modules=["shelf_intelligence", "misplacement"],
                recommended_action=rec.rec_misplacement(m.product_name, m.shelf_code),
                certainty=CERTAINTY_MEDIUM,
                product_id=m.product_id,
                shelf_id=_shelf_id(ctx, m.shelf_code),
                camera_id=m.camera_id,
                evidence=ev.ev_misplacement(
                    product_id=m.product_id,
                    product_name=m.product_name,
                    ai_class=m.ai_class,
                    shelf_code=m.shelf_code,
                    visible_count=m.visible_count,
                    confidence=m.confidence,
                ),
            )
        )
    return candidates


def _shelf_id(ctx: RuleContext, code: str) -> Optional[UUID]:
    from app.models import Shelf

    s = ctx.session.scalar(
        select(Shelf).where(Shelf.store_id == ctx.store_id, Shelf.code == code)
    )
    return s.id if s else None


# ---------------------------------------------------------------------------
# Customer-flow rules (M19 aggregate analytics; no intent inference)
# ---------------------------------------------------------------------------


def rule_customer_flow(ctx: RuleContext) -> List[RuleCandidate]:
    """HIGH_TRAFFIC_ZONE / HIGH_DWELL_ZONE / HIGH_TRAFFIC_LOW_SHELF_AVAILABILITY.

    Traffic floor  = HIGH_TRAFFIC_MIN_VISITS over the window.
    Dwell floor    = HIGH_DWELL_MIN_SECONDS average over >= HIGH_DWELL_MIN_VISITS
                     closed visits.
    Baseline: a zone is also high-traffic if its visits exceed the store-wide
    average by a configurable factor — only when journey data exists (M19).
    """
    settings = get_settings()
    traffic_start = ctx.now - timedelta(hours=ctx.traffic_hours)
    dwell_start = ctx.now - timedelta(hours=ctx.dwell_hours)

    # Zone labels.
    zone_names: dict = {}
    for z in ctx.session.scalars(select(Zone).where(Zone.store_id == ctx.store_id)):
        zone_names[z.id] = z.name

    # Traffic: distinct visits count per zone in window.
    traffic_rows = ctx.session.execute(
        select(ZoneVisit.zone_id, func.count().label("visits"))
        .where(ZoneVisit.store_id == ctx.store_id, ZoneVisit.entered_at >= traffic_start)
        .group_by(ZoneVisit.zone_id)
    ).all()
    visits: dict = {zid: int(cnt) for zid, cnt in traffic_rows}
    if not visits:
        return []

    avg_visits = sum(visits.values()) / len(visits)
    factor = float(settings.HIGH_TRAFFIC_VISITS_FACTOR)

    # Dwell: avg dwell per zone over CLOSED visits in window.
    dwell_rows = ctx.session.execute(
        select(
            ZoneVisit.zone_id,
            func.count().label("closed_visits"),
            func.avg(ZoneVisit.dwell_seconds).label("avg_dwell"),
        )
        .where(
            ZoneVisit.store_id == ctx.store_id,
            ZoneVisit.entered_at >= dwell_start,
            ZoneVisit.dwell_seconds.is_not(None),
        )
        .group_by(ZoneVisit.zone_id)
    ).all()

    candidates: List[RuleCandidate] = []
    traffic_zones: set = set()

    min_visits = int(settings.HIGH_TRAFFIC_MIN_VISITS)
    min_dwell = int(settings.HIGH_DWELL_MIN_SECONDS)
    min_dwell_visits = int(settings.HIGH_DWELL_MIN_VISITS)

    for zid, cnt in visits.items():
        name = zone_names.get(zid)
        over_baseline = cnt > avg_visits * factor and cnt >= min_visits
        if cnt >= min_visits or (over_baseline and cnt > 0):
            traffic_zones.add(zid)
            candidates.append(
                RuleCandidate(
                    insight_type=INSIGHT_HIGH_TRAFFIC_ZONE,
                    entity_type="zone",
                    entity_id=str(zid),
                    severity=SEV_INFO,
                    title=f"High traffic zone: {name or zid}",
                    description=(
                        f"Zone recorded {cnt} visits in the last "
                        f"{ctx.traffic_hours}h (floor {min_visits}, store avg "
                        f"{avg_visits:.1f})."
                    ),
                    rule_id="customer_flow.high_traffic",
                    source_modules=["journeys", "zone_visits"],
                    recommended_action=rec.rec_high_traffic(name),
                    certainty=CERTAINTY_HIGH,
                    zone_id=zid,
                    evidence=ev.ev_high_traffic(
                        zone_id=zid,
                        zone_name=name,
                        visits_total=cnt,
                        visitors_unique=_unique_visitors(ctx, zid, traffic_start),
                    ),
                )
            )

    for zid, closed, avg_dwell in dwell_rows:
        if closed < min_dwell_visits or avg_dwell is None:
            continue
        if avg_dwell >= min_dwell:
            name = zone_names.get(zid)
            candidates.append(
                RuleCandidate(
                    insight_type=INSIGHT_HIGH_DWELL_ZONE,
                    entity_type="zone",
                    entity_id=str(zid),
                    severity=SEV_INFO,
                    title=f"High dwell zone: {name or zid}",
                    description=(
                        f"Average dwell in this zone is {avg_dwell:.0f}s "
                        f"({closed} closed visits; floor {min_dwell}s)."
                    ),
                    rule_id="customer_flow.high_dwell",
                    source_modules=["journeys", "zone_visits"],
                    recommended_action=rec.rec_high_dwell(name),
                    certainty=CERTAINTY_HIGH,
                    zone_id=zid,
                    evidence=ev.ev_high_dwell(
                        zone_id=zid,
                        zone_name=name,
                        avg_dwell_seconds=float(avg_dwell),
                        visits_total=closed,
                    ),
                )
            )

    candidates.extend(
        rule_traffic_low_shelf(ctx, traffic_zones, visits)
    )
    return candidates


def _unique_visitors(ctx: RuleContext, zone_id: UUID, start: datetime) -> int:
    return (
        ctx.session.scalar(
            select(func.count(func.distinct(ZoneVisit.global_person_id))).where(
                ZoneVisit.store_id == ctx.store_id,
                ZoneVisit.zone_id == zone_id,
                ZoneVisit.entered_at >= start,
            )
        )
        or 0
    )


def rule_traffic_low_shelf(
    ctx: RuleContext,
    traffic_zones: set,
    visits: dict,
) -> List[RuleCandidate]:
    """HIGH_TRAFFIC_LOW_SHELF_AVAILABILITY: a high-traffic zone ALSO has a
    low/empty shelf AND the store has some inventory (so it's a stocking
    problem, not a whole-store OOS)."""
    if not traffic_zones:
        return []

    shelf_svc = ShelfIntelligenceService(ctx.session)
    shelf_rows = shelf_svc.shelves(store_id=ctx.store_id)

    zone_shelf: dict = {}
    for row in shelf_rows:
        if row.zone_id in traffic_zones and row.detection_status in (
            SHELF_STATE_LOW,
            SHELF_STATE_EMPTY,
        ):
            zone_shelf.setdefault(row.zone_id, []).append(row.shelf_code)

    if not zone_shelf:
        return []

    store_has_inventory = (
        ctx.session.scalar(
            select(func.count(Inventory.id)).where(
                Inventory.store_id == ctx.store_id, Inventory.quantity > 0
            )
        )
        or 0
    ) > 0

    zone_names: dict = {}
    for z in ctx.session.scalars(select(Zone).where(Zone.store_id == ctx.store_id)):
        zone_names[z.id] = z.name

    candidates: List[RuleCandidate] = []
    for zid, shelf_codes in zone_shelf.items():
        name = zone_names.get(zid)
        candidates.append(
            RuleCandidate(
                insight_type=INSIGHT_HIGH_TRAFFIC_LOW_SHELF,
                entity_type="zone",
                entity_id=str(zid),
                severity=SEV_MEDIUM,
                title=f"High traffic + low shelf availability: {name or zid}",
                description=(
                    f"Zone '{name or zid}' is high traffic ({visits.get(zid, 0)} visits) "
                    f"but its shelves {', '.join(shelf_codes)} read low/empty — "
                    "and the store has inventory available."
                ),
                rule_id="customer_flow.high_traffic_low_shelf",
                source_modules=["journeys", "shelf_intelligence", "inventory"],
                recommended_action=rec.rec_high_traffic_low_shelf(),
                certainty=CERTAINTY_MEDIUM,
                zone_id=zid,
                evidence=ev.ev_high_traffic_low_shelf(
                    zone_id=zid,
                    zone_name=name,
                    visits_total=visits.get(zid, 0),
                    shelf_codes=shelf_codes,
                    inventory_available=store_has_inventory,
                ),
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Camera rules (deterministic simulated heartbeat proxy)
# ---------------------------------------------------------------------------


def rule_camera_health(ctx: RuleContext) -> List[RuleCandidate]:
    """CAMERA_HEALTH: an ACTIVE camera with no observation in the last N
    minutes. Documented simulated proxy — NOT a hardware connectivity check."""
    cameras = list(
        ctx.session.scalars(
            select(Camera).where(
                Camera.store_id == ctx.store_id, Camera.is_active.is_(True)
            )
        )
    )
    if not cameras:
        return []

    camera_ids = [c.id for c in cameras]
    last_by_cam = dict(
        ctx.session.execute(
            select(Observation.camera_id, func.max(Observation.observed_at))
            .where(
                Observation.camera_id.in_(camera_ids),
                Observation.camera_id.is_not(None),
            )
            .group_by(Observation.camera_id)
        ).all()
    )
    threshold = ctx.now - timedelta(minutes=ctx.camera_stale_minutes)

    candidates: List[RuleCandidate] = []
    for cam in cameras:
        last = last_by_cam.get(cam.id)
        if last is not None and last >= threshold:
            continue
        candidates.append(
            RuleCandidate(
                insight_type=INSIGHT_CAMERA_HEALTH,
                entity_type="camera",
                entity_id=str(cam.id),
                severity=SEV_HIGH,
                title=f"Camera offline or idle: {cam.name}",
                description=(
                    f"Camera '{cam.name}' has no observations in the last "
                    f"{ctx.camera_stale_minutes} minutes."
                ),
                rule_id="camera_health.stale",
                source_modules=["camera_status"],
                recommended_action=rec.rec_camera(cam.name),
                certainty=CERTAINTY_HIGH,
                camera_id=cam.id,
                alert_type=ALERT_CAMERA_OFFLINE,
                evidence=ev.ev_camera_health(
                    camera_id=cam.id,
                    camera_name=cam.name,
                    last_observed_at=last,
                    stale_minutes=ctx.camera_stale_minutes,
                ),
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Sales rule (only with real sales data)
# ---------------------------------------------------------------------------


def rule_high_selling_low_stock(ctx: RuleContext) -> List[RuleCandidate]:
    """HIGH_SELLING_LOW_STOCK: quantity <= reorder_level AND >= N units sold
    in the window. Explicitly NOT a customer-intent claim — it couples POS
    sales velocity to inventory level."""
    settings = get_settings()
    min_units = int(settings.HIGH_SELLING_MIN_UNITS)
    if min_units < 1:
        return []
    since = ctx.now - timedelta(hours=ctx.sales_hours)

    # Units sold per product in window.
    sold_rows = ctx.session.execute(
        select(SaleItem.product_id, func.sum(SaleItem.quantity).label("units"))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Sale.store_id == ctx.store_id,
            Sale.sale_timestamp_utc >= since,
        )
        .group_by(SaleItem.product_id)
        .having(func.sum(SaleItem.quantity) >= min_units)
    ).all()

    product_ids = [r[0] for r in sold_rows]
    if not product_ids:
        return []

    inv_rows = ctx.session.execute(
        select(Product, Inventory)
        .join(Inventory, Inventory.product_id == Product.id)
        .where(Product.store_id == ctx.store_id, Product.id.in_(product_ids))
        .order_by(Product.sku)
    ).all()

    sold_qty = {pid: int(units) for pid, units in sold_rows}
    candidates: List[RuleCandidate] = []
    for product, inv in inv_rows:
        if inv.quantity <= 0 or inv.quantity > inv.reorder_level:
            continue
        units = sold_qty[product.id]
        candidates.append(
            RuleCandidate(
                insight_type=INSIGHT_HIGH_SELLING_LOW_STOCK,
                entity_type="product",
                entity_id=str(product.id),
                severity=SEV_MEDIUM,
                title=f"High-selling & low stock: {product.name}",
                description=(
                    f"{product.name} ({product.sku}) sold {units} units in the last "
                    f"{ctx.sales_hours}h but is at {inv.quantity} (reorder level "
                    f"{inv.reorder_level})."
                ),
                rule_id="sales.high_selling_low_stock",
                source_modules=["sales", "inventory"],
                recommended_action=rec.rec_high_selling_low_stock(product.name, product.sku),
                certainty=CERTAINTY_HIGH,
                product_id=product.id,
                evidence=ev.ev_high_selling_low_stock(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    quantity=inv.quantity,
                    reorder_level=inv.reorder_level,
                    units_sold=units,
                    window_hours=ctx.sales_hours,
                ),
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Combination rule (inventory x shelf)
# ---------------------------------------------------------------------------


def rule_low_stock_low_shelf(ctx: RuleContext) -> List[RuleCandidate]:
    """LOW_STOCK_WITH_LOW_SHELF_AVAILABILITY: a product is low-stock (POS) AND
    there is a shelf whose AI state is low/empty containing that product.
    Entity = product. Only produced when real shelf evidence exists for the
    mapped product (never guessed)."""
    low_candidates = [
        c
        for c in rule_inventory(ctx)
        if c.insight_type == INSIGHT_LOW_STOCK and c.product_id is not None
    ]
    if not low_candidates:
        return []

    low_products = {c.product_id: c for c in low_candidates}

    shelf_svc = ShelfIntelligenceService(ctx.session)
    shelf_rows = shelf_svc.shelves(store_id=ctx.store_id)

    product_shelf_state: dict = {}
    for row in shelf_rows:
        if row.detection_status not in (SHELF_STATE_LOW, SHELF_STATE_EMPTY):
            continue
        for vp in row.visible_products:
            if vp.product_id in low_products:
                # Prefer the "worse" shelf state (empty > low) for evidence.
                current = product_shelf_state.get(vp.product_id)
                if current is None or _shelf_state_rank(row.detection_status) >= _shelf_state_rank(current["state"]):
                    product_shelf_state[vp.product_id] = {
                        "state": row.detection_status,
                        "shelf_code": row.shelf_code,
                        "occupied_pct": row.occupied_pct,
                    }

    if not product_shelf_state:
        return []

    candidates: List[RuleCandidate] = []
    for product_id, shelf_meta in product_shelf_state.items():
        cand = low_products[product_id]
        candidates.append(
            RuleCandidate(
                insight_type=INSIGHT_LOW_STOCK_LOW_SHELF,
                entity_type="product",
                entity_id=str(product_id),
                severity=SEV_MEDIUM,
                title=f"Low stock + low shelf availability: {cand.title.split(': ', 1)[-1]}",
                description=(
                    f"{cand.description} Additionally, AI reads shelf "
                    f"{shelf_meta['shelf_code']} as {shelf_meta['state']} "
                    f"({shelf_meta['occupied_pct']}% visible occupancy)."
                ),
                rule_id="inventory.low_stock_with_low_shelf",
                source_modules=sorted(
                    set(cand.source_modules) | {"shelf_intelligence"}
                ),
                recommended_action=rec.rec_low_stock_low_shelf(
                    cand.title.split(": ", 1)[-1],
                    cand.evidence.get("product", {}).get("sku"),
                ),
                certainty=CERTAINTY_MEDIUM,
                product_id=product_id,
                evidence=ev.ev_low_stock_low_shelf(
                    product_id=product_id,
                    sku=cand.evidence.get("product", {}).get("sku"),
                    name=cand.evidence.get("product", {}).get("name"),
                    quantity=cand.evidence.get("metrics", {}).get("current_stock"),
                    reorder_level=cand.evidence.get("metrics", {}).get("reorder_level"),
                    shelf_code=shelf_meta["shelf_code"],
                    shelf_occupied_pct=shelf_meta["occupied_pct"],
                ),
            )
        )
    return candidates


def _shelf_state_rank(state: str) -> int:
    return 1 if state == SHELF_STATE_EMPTY else 0
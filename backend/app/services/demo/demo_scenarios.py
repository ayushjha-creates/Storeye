"""Deterministic scenario overlays for the demo store (M21).

Each overlay runs AFTER a full baseline reset, mutates ONLY demo-store rows
through the domain tables/services, then the engine clears derived
insights/alerts and re-evaluates — so the same scenario always produces the
same state and never contaminates another scenario.

Hard rules honoured here:
    * only rows whose store is the demo store are touched,
    * inventory/batches are changed as DEMO DATA (never by the M20 engine),
    * no OCR is run, no CV model is invoked, no cloud service is contacted,
    * people flow is aggregate only and never translated into intent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    Batch,
    Camera,
    CONF_MEDIUM,
    Insight,
    Inventory,
    OBS_PERSON,
    OBS_PRODUCT,
    Observation,
    Product,
    Store,
    Zone,
    ZoneVisit,
)
from scripts.seed_demo import fixed

from . import demo_data as data


# ---------------------------------------------------------------------------
# small primitives
# ---------------------------------------------------------------------------


def _ensure_obs(
    session: Session,
    *,
    key: str,
    store_id: UUID,
    camera_id: Optional[UUID],
    observation_type: str,
    class_name: str,
    track_id: int,
    bbox: Optional[List[float]],
    observed_at: datetime,
    confidence: float = 0.95,
) -> None:
    obs_id = fixed(key)
    if session.get(Observation, obs_id) is not None:
        return
    session.add(
        Observation(
            id=obs_id,
            store_id=store_id,
            camera_id=camera_id,
            observation_type=observation_type,
            track_id=track_id,
            bbox=bbox,
            confidence=confidence,
            source="demo-scenario",
            observed_at=observed_at,
            details={"class_name": class_name, "label": class_name},
        )
    )


def _cameras(session: Session, store: Store) -> Dict[str, Camera]:
    return {
        c.name: c
        for c in session.scalars(select(Camera).where(Camera.store_id == store.id))
    }


def _zones(session: Session, store: Store) -> Dict[str, Zone]:
    return {
        z.name: z
        for z in session.scalars(select(Zone).where(Zone.store_id == store.id))
    }


def _shelf_camera(session: Session, store: Store) -> Optional[Camera]:
    for cam in session.scalars(select(Camera).where(Camera.store_id == store.id)):
        regions = (cam.config or {}).get("shelf_regions")
        if isinstance(regions, list) and regions:
            return cam
    return None


def _clear_derived(session: Session, store: Store) -> None:
    """Remove derived M16/M20 rows so a scenario starts from a clean slate."""
    session.execute(delete(Alert).where(Alert.store_id == store.id))
    session.execute(delete(Insight).where(Insight.store_id == store.id))


def _neutralize_inventory(session: Session, store: Store) -> None:
    """Push every stocked product comfortably above its reorder level."""
    session.execute(
        update(Inventory)
        .where(Inventory.store_id == store.id)
        .values(quantity=func.greatest(Inventory.reorder_level + 20, 30))
    )


def _neutralize_batches(session: Session, store: Store, now: datetime) -> None:
    """Move every batch expiry far into the future (no expiry risk)."""
    session.execute(
        update(Batch)
        .where(Batch.store_id == store.id)
        .values(expiry_date=now.date() + timedelta(days=400))
    )


def _write_shelf_plan(
    session: Session,
    store: Store,
    now: datetime,
    plan: Sequence[Tuple[str, str, List[float], int]],
    *,
    delete_existing: bool = True,
) -> int:
    """Replace (or append) product observations to realise a shelf plan."""
    if delete_existing:
        session.execute(
            delete(Observation).where(
                Observation.store_id == store.id,
                Observation.observation_type == OBS_PRODUCT,
            )
        )
    cam = _shelf_camera(session, store)
    if cam is None:
        return 0
    written = 0
    for code, cls, bbox, track in plan:
        _ensure_obs(
            session,
            key=f"scenario:obs:{code}:{track}",
            store_id=store.id,
            camera_id=cam.id,
            observation_type=OBS_PRODUCT,
            class_name=cls,
            track_id=track,
            bbox=list(bbox),
            observed_at=now,
        )
        written += 1
    return written


def _neutralize_cameras(
    session: Session,
    store: Store,
    now: datetime,
    *,
    skip_names: Iterable[str] = (),
) -> None:
    """Give every active camera a fresh observation (heartbeat proxy) except
    the ones the scenario wants offline."""
    skip = set(skip_names)
    for cam in _cameras(session, store).values():
        if not cam.is_active or cam.name in skip:
            continue
        _ensure_obs(
            session,
            key=f"scenario:cam:{cam.id}",
            store_id=store.id,
            camera_id=cam.id,
            observation_type=OBS_PERSON,
            class_name="person",
            track_id=7999,
            bbox=[10.0, 10.0, 20.0, 40.0],
            observed_at=now,
        )


def _neutralize(
    session: Session,
    store: Store,
    now: datetime,
    *,
    shelf_plan: Optional[Sequence[Tuple[str, str, List[float], int]]] = None,
    skip_camera_names: Iterable[str] = (),
) -> None:
    """Turn the rich baseline into a healthy store, then clear derived rows."""
    _neutralize_inventory(session, store)
    _neutralize_batches(session, store, now)
    _write_shelf_plan(
        session, store, now,
        shelf_plan if shelf_plan is not None else data.NEUTRAL_SHELF_OBSERVATIONS,
    )
    _neutralize_cameras(session, store, now, skip_names=skip_camera_names)
    _clear_derived(session, store)


def _inventory(session: Session, store: Store, sku: str) -> Optional[Inventory]:
    product = session.scalars(
        select(Product).where(Product.store_id == store.id, Product.sku == sku)
    ).first()
    if product is None:
        return None
    return session.scalars(
        select(Inventory).where(
            Inventory.store_id == store.id, Inventory.product_id == product.id
        )
    ).first()


def _set_inventory(session: Session, store: Store, sku: str, quantity: int) -> bool:
    inv = _inventory(session, store, sku)
    if inv is None:
        return False
    inv.quantity = quantity
    return True


def _set_batch_expiry(
    session: Session, store: Store, sku: str, batch_number: str, expiry
) -> bool:
    product = session.scalars(
        select(Product).where(Product.store_id == store.id, Product.sku == sku)
    ).first()
    if product is None:
        return False
    batch = session.scalars(
        select(Batch).where(
            Batch.store_id == store.id,
            Batch.product_id == product.id,
            Batch.batch_number == batch_number,
        )
    ).first()
    if batch is None:
        return False
    batch.expiry_date = expiry
    batch.expiry_date_precision = "day"
    return True


def _insert_zone_visits(
    session: Session,
    store: Store,
    *,
    zone: Zone,
    camera: Optional[Camera],
    count: int,
    dwell_seconds: float,
    prefix: str,
    now: datetime,
) -> int:
    created = 0
    for i in range(count):
        vid = fixed(f"scenario:visit:{prefix}:{i}")
        if session.get(ZoneVisit, vid) is not None:
            continue
        entered = now - timedelta(minutes=3 * i + 1)
        session.add(
            ZoneVisit(
                id=vid,
                store_id=store.id,
                global_person_id=f"demo-{prefix}-{i:04d}",
                zone_id=zone.id,
                camera_id=camera.id if camera else None,
                entered_at=entered,
                exited_at=entered + timedelta(seconds=dwell_seconds),
                dwell_seconds=dwell_seconds,
                confidence=CONF_MEDIUM,
            )
        )
        created += 1
    return created


# ---------------------------------------------------------------------------
# scenario overlays
# ---------------------------------------------------------------------------


def apply_normal(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now)
    return {"neutralized": True}


def apply_low_stock(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now)
    ok = _set_inventory(session, store, "MAGGI-2MIN", 8)
    return {"low_stock_product": "MAGGI-2MIN", "quantity": 8, "applied": ok}


def apply_out_of_stock(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now)
    ok = _set_inventory(session, store, "BRIT-BREAD", 0)
    return {"out_of_stock_product": "BRIT-BREAD", "quantity": 0, "applied": ok}


def apply_expiry_risk(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now)
    soon = now.date() + timedelta(days=10)
    expired = now.date() - timedelta(days=3)
    a = _set_batch_expiry(session, store, "AMUL-MILK", "AMUL-2", soon)
    b = _set_batch_expiry(session, store, "AMUL-MILK", "AMUL-1", expired)
    return {"expiring_soon": str(soon), "expired": str(expired), "applied": a and b}


def apply_low_shelf_backstock(session: Session, store: Store, now: datetime) -> dict:
    plan = [e for e in data.NEUTRAL_SHELF_OBSERVATIONS if e[0] != "A2"]
    plan += data.LOW_SHELF_OBSERVATIONS
    _neutralize(session, store, now, shelf_plan=plan)
    return {"low_shelf": "A2", "inventory_available": True}


def apply_misplacement(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now)
    written = _write_shelf_plan(
        session, store, now, data.MISPLACEMENT_OBSERVATIONS, delete_existing=False
    )
    return {"misplaced_product": "MAGGI-2MIN", "shelf": "B2", "written": written}


def apply_high_traffic(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now)
    zones = _zones(session, store)
    cams = _cameras(session, store)
    grocery = zones.get("Grocery & Staples")
    if grocery is None:
        return {"high_traffic_zone": None, "visits": 0}
    created = _insert_zone_visits(
        session, store, zone=grocery, camera=cams.get("Demo Aisle Cam"),
        count=data.HIGH_TRAFFIC_VISIT_COUNT,
        dwell_seconds=data.HIGH_TRAFFIC_DWELL_SECONDS,
        prefix="traffic", now=now,
    )
    return {"high_traffic_zone": grocery.name, "visits": created}


def apply_high_dwell(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now)
    zones = _zones(session, store)
    cams = _cameras(session, store)
    bev = zones.get("Beverages")
    if bev is None:
        return {"high_dwell_zone": None, "visits": 0}
    created = _insert_zone_visits(
        session, store, zone=bev, camera=cams.get("Demo Aisle Cam"),
        count=data.HIGH_DWELL_VISIT_COUNT,
        dwell_seconds=data.HIGH_DWELL_DWELL_SECONDS,
        prefix="dwell", now=now,
    )
    return {
        "high_dwell_zone": bev.name,
        "visits": created,
        "avg_dwell_seconds": data.HIGH_DWELL_DWELL_SECONDS,
    }


def apply_multi_camera_journey(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now)
    return {"multi_camera": True, "cameras": ["Demo Entrance Cam", "Demo Aisle Cam", "Demo Till Cam"]}


def apply_camera_offline(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now, skip_camera_names={"Demo Roof Cam"})
    return {"offline_camera": "Demo Roof Cam"}


def apply_smart_receiving(session: Session, store: Store, now: datetime) -> dict:
    _neutralize(session, store, now)
    return {"workflow": "M17 receive", "note": "Run the real close-up scan workflow."}


def apply_combined_crisis(session: Session, store: Store, now: datetime) -> dict:
    # Keep the rich M18/M20 baseline exactly as seeded (multiple simultaneous
    # problems). The engine re-evaluates so derived rows are fresh.
    return {"baseline_crisis": True}


APPLIERS = {
    data.SCENARIO_NORMAL: apply_normal,
    data.SCENARIO_LOW_STOCK: apply_low_stock,
    data.SCENARIO_OUT_OF_STOCK: apply_out_of_stock,
    data.SCENARIO_EXPIRY_RISK: apply_expiry_risk,
    data.SCENARIO_LOW_SHELF_BACKSTOCK: apply_low_shelf_backstock,
    data.SCENARIO_MISPLACEMENT: apply_misplacement,
    data.SCENARIO_HIGH_TRAFFIC: apply_high_traffic,
    data.SCENARIO_HIGH_DWELL: apply_high_dwell,
    data.SCENARIO_MULTI_CAMERA_JOURNEY: apply_multi_camera_journey,
    data.SCENARIO_CAMERA_OFFLINE: apply_camera_offline,
    data.SCENARIO_SMART_RECEIVING: apply_smart_receiving,
    data.SCENARIO_COMBINED_CRISIS: apply_combined_crisis,
}

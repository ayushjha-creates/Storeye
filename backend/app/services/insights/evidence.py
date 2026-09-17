"""Evidence builders for the M20 Store Intelligence engine.

Every insight carries a human-readable `evidence` dict (JSONB in PG) that
exactly answers the "Why was this insight generated?" question. The frontend
renders a "Reason / Why?" drawer from this structure.

Every evidence dict follows this documented shape so the frontend can render
it uniformly:

    {
        "rule":     rule_id,
        "summary":  [human-readable lines, first is the headline],
        "sources":  list[str]  — modules that contributed data,
        "metrics":  {label: value, ...}  — structured key/value pairs,
        ...rule-specific typed sections (product, inventory, batch, etc.)
    }

The structure is OPEN to rule-specific additions; the frontend MUST NOT
fail if extra/unknown keys are present.
"""

from __future__ import annotations

from typing import List, Optional, Union
from uuid import UUID


def _str(v: Optional[Union[str, UUID]]) -> Optional[str]:
    return str(v) if v is not None else None


def evidence_head(
    *,
    rule: str,
    summary: List[str],
    sources: List[str],
    metrics: Optional[dict] = None,
    **extra: dict,
) -> dict:
    """Base evidence dict shared by every insight type."""
    body: dict = {
        "rule": rule,
        "summary": summary,
        "sources": sources,
        "metrics": metrics or {},
    }
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Per-rule evidence builders.  Every function returns a ready-to-attach dict.
# ---------------------------------------------------------------------------


def ev_low_stock(
    *,
    product_id: Optional[UUID],
    sku: str,
    name: str,
    quantity: int,
    reorder_level: int,
    reorder_quantity: int,
) -> dict:
    return evidence_head(
        rule="low_stock",
        summary=[
            f"{name} ({sku}): current stock {quantity} units "
            f"(reorder level: {reorder_level}).",
            "Stock is low — consider placing a purchase order.",
        ],
        sources=["inventory"],
        metrics={
            "current_stock": quantity,
            "reorder_level": reorder_level,
            "reorder_quantity": reorder_quantity,
        },
        product={"id": _str(product_id), "sku": sku, "name": name},
    )


def ev_out_of_stock(
    *,
    product_id: Optional[UUID],
    sku: str,
    name: str,
    quantity: int,
    reorder_level: int,
) -> dict:
    return evidence_head(
        rule="out_of_stock",
        summary=[
            f"{name} ({sku}): current stock is {quantity} units (REORDER IMMEDIATELY).",
        ],
        sources=["inventory"],
        metrics={
            "current_stock": quantity,
            "reorder_level": reorder_level,
        },
        product={"id": _str(product_id), "sku": sku, "name": name},
    )


def ev_expiry_risk(
    *,
    product_id: Optional[UUID],
    sku: str,
    name: str,
    batch_id: Optional[UUID],
    batch_number: Optional[str],
    expiry_date,
    precision: str,
    days_until_expiry: Optional[int],
    status: str,
) -> dict:
    return evidence_head(
        rule="expiry_risk",
        summary=[
            f"{name} (batch {batch_number or 'n/a'}): "
            f"expiry {expiry_date} ({precision} precision).",
            f"Status: {status}. Review and rotate stock before expiry.",
        ],
        sources=["expiry_intelligence"],
        metrics={
            "batch_number": batch_number,
            "expiry_date": str(expiry_date) if expiry_date else None,
            "expiry_date_precision": precision,
            "days_until_expiry": days_until_expiry,
            "expiry_status": status,
        },
        batch={"id": _str(batch_id), "number": batch_number},
        product={"id": _str(product_id), "sku": sku, "name": name},
    )


def ev_expired_batch(
    *,
    product_id: Optional[UUID],
    sku: str,
    name: str,
    batch_id: Optional[UUID],
    batch_number: Optional[str],
    expiry_date,
    precision: str,
) -> dict:
    return evidence_head(
        rule="expired_batch",
        summary=[
            f"{name} (batch {batch_number or 'n/a'}): expired on {expiry_date}.",
            "Remove from shelves immediately and arrange return/disposal.",
        ],
        sources=["expiry_intelligence"],
        metrics={
            "batch_number": batch_number,
            "expiry_date": str(expiry_date) if expiry_date else None,
            "expiry_date_precision": precision,
        },
        batch={"id": _str(batch_id), "number": batch_number},
        product={"id": _str(product_id), "sku": sku, "name": name},
    )


def ev_stock_rotation(
    *,
    product_id: Optional[UUID],
    sku: str,
    name: str,
    batches: List[dict],
) -> dict:
    return evidence_head(
        rule="stock_rotation_recommendation",
        summary=[
            f"{name} ({sku}) has {len(batches)} batches with stock — "
            "rotate earliest-expiring batches to shelf front first.",
        ],
        sources=["expiry_intelligence"],
        metrics={"batch_count": len(batches)},
        batches=batches,
        product={"id": _str(product_id), "sku": sku, "name": name},
    )


def ev_low_shelf(
    *,
    shelf_code: str,
    zone_name: Optional[str],
    detection_status: str,
    occupied_pct: Optional[float],
    camera_name: Optional[str],
) -> dict:
    label = "EMPTY — AI sees no product" if detection_status == "EMPTY_VISIBLE" else "LOW occupancy"
    return evidence_head(
        rule="low_shelf_availability",
        summary=[
            f"Shelf {shelf_code}: {label} "
            f"(estimated visible occupancy {occupied_pct}%).",
            "AI-estimated occupancy is informational — review stock levels.",
        ],
        sources=["shelf_intelligence"],
        metrics={
            "shelf_code": shelf_code,
            "zone_name": zone_name,
            "detection_status": detection_status,
            "occupied_pct": occupied_pct,
            "camera_name": camera_name,
        },
        shelf={"code": shelf_code, "zone_name": zone_name, "camera_name": camera_name},
    )


def ev_misplacement(
    *,
    product_id: Optional[UUID],
    product_name: Optional[str],
    ai_class: str,
    shelf_code: str,
    visible_count: int,
    confidence: Optional[float],
) -> dict:
    return evidence_head(
        rule="misplacement",
        summary=[
            f"AI detects {product_name or ai_class} on shelf {shelf_code} "
            f"({visible_count} visible) — this shelf's planogram expects "
            "other products.",
        ],
        sources=["shelf_intelligence"],
        metrics={
            "ai_class": ai_class,
            "visible_count": visible_count,
            "confidence": confidence,
            "shelf_code": shelf_code,
        },
        product={"id": _str(product_id), "name": product_name, "ai_class": ai_class},
        shelf={"code": shelf_code},
    )


def ev_high_traffic(
    *,
    zone_id: Optional[UUID],
    zone_name: Optional[str],
    visits_total: int,
    visitors_unique: int,
) -> dict:
    return evidence_head(
        rule="high_traffic_zone",
        summary=[
            f"Zone '{zone_name}' recorded {visits_total} zone visits "
            f"({visitors_unique} unique visitors) — above configured "
            "traffic floor.",
        ],
        sources=["journeys"],
        metrics={
            "visits_total": visits_total,
            "visitors_unique": visitors_unique,
        },
        zone={"id": _str(zone_id), "name": zone_name},
    )


def ev_high_dwell(
    *,
    zone_id: Optional[UUID],
    zone_name: Optional[str],
    avg_dwell_seconds: Optional[float],
    visits_total: int,
) -> dict:
    return evidence_head(
        rule="high_dwell_zone",
        summary=[
            f"Zone '{zone_name}': average dwell {avg_dwell_seconds:.0f}s "
            f"across {visits_total} closed visits — above configured dwell "
            "floor.",
        ],
        sources=["journeys"],
        metrics={
            "avg_dwell_seconds": round(avg_dwell_seconds, 2) if avg_dwell_seconds else None,
            "visits_total": visits_total,
        },
        zone={"id": _str(zone_id), "name": zone_name},
    )


def ev_high_traffic_low_shelf(
    *,
    zone_id: Optional[UUID],
    zone_name: Optional[str],
    visits_total: int,
    shelf_codes: List[str],
    inventory_available: bool,
) -> dict:
    inv_msg = (
        "Stock is available in store — these shelves may need replenishing "
        "or shelf rearrangement."
        if inventory_available
        else "No store inventory detected for any product — a broader OOS situation may exist."
    )
    return evidence_head(
        rule="high_traffic_low_shelf_availability",
        summary=[
            f"Zone '{zone_name}': high traffic ({visits_total} visits) "
            f"combined with low shelf availability on: {', '.join(shelf_codes)}.",
            inv_msg,
        ],
        sources=["journeys", "shelf_intelligence", "inventory"],
        metrics={
            "visits_total": visits_total,
            "low_shelf_codes": shelf_codes,
            "inventory_available": inventory_available,
        },
        zone={"id": _str(zone_id), "name": zone_name},
    )


def ev_camera_health(
    *,
    camera_id: Optional[UUID],
    camera_name: Optional[str],
    last_observed_at,
    stale_minutes: int,
) -> dict:
    return evidence_head(
        rule="camera_health",
        summary=[
            f"Camera '{camera_name}' has no observations in the last "
            f"{stale_minutes} minutes."
            + (
                f" Last observation: {last_observed_at.isoformat()}."
                if last_observed_at
                else " No observations found."
            ),
            "This is a simulated stale-heartbeat proxy, not a hardware check.",
        ],
        sources=["camera_status"],
        metrics={
            "last_observed_at": last_observed_at.isoformat() if last_observed_at else None,
            "stale_minutes": stale_minutes,
        },
        camera={"id": _str(camera_id), "name": camera_name},
    )


def ev_high_selling_low_stock(
    *,
    product_id: Optional[UUID],
    sku: str,
    name: str,
    quantity: int,
    reorder_level: int,
    units_sold: int,
    window_hours: int,
) -> dict:
    return evidence_head(
        rule="high_selling_low_stock",
        summary=[
            f"{name} ({sku}): sold {units_sold} units in {window_hours}h "
            f"but current stock is {quantity} (reorder level: {reorder_level}).",
            "High sales velocity with low stock — restock promptly.",
        ],
        sources=["sales", "inventory"],
        metrics={
            "units_sold": units_sold,
            "window_hours": window_hours,
            "current_stock": quantity,
            "reorder_level": reorder_level,
        },
        product={"id": _str(product_id), "sku": sku, "name": name},
    )


def ev_low_stock_low_shelf(
    *,
    product_id: Optional[UUID],
    sku: str,
    name: str,
    quantity: int,
    reorder_level: int,
    shelf_code: str,
    shelf_occupied_pct: Optional[float],
) -> dict:
    return evidence_head(
        rule="low_stock_low_shelf_availability",
        summary=[
            f"{name} ({sku}): low stock ({quantity} units, reorder level "
            f"{reorder_level}) AND low visible shelf availability on "
            f"shelf {shelf_code} ({shelf_occupied_pct}% occupancy).",
            "Replenish from backroom and verify shelf presentation.",
        ],
        sources=["inventory", "shelf_intelligence"],
        metrics={
            "current_stock": quantity,
            "reorder_level": reorder_level,
            "shelf_code": shelf_code,
            "occupied_pct": shelf_occupied_pct,
        },
        product={"id": _str(product_id), "sku": sku, "name": name},
        shelf={"code": shelf_code, "occupied_pct": shelf_occupied_pct},
    )


def ev_store_health(
    *,
    state: str,
    cameras: dict,
    inventory: dict,
    shelf: dict,
    alerts: dict,
    expiry: dict,
    customer_flow: dict,
) -> dict:
    return evidence_head(
        rule="store_health",
        summary=[
            f"Store health: {state}.",
            "Categorical state driven by current active insights (no opaque score).",
        ],
        sources=["inventory", "shelf_intelligence", "expiry_intelligence", "journeys", "alerts", "camera_status"],
        metrics={
            "cameras_healthy_pct": cameras.get("healthy_pct"),
            "inventory_healthy_pct": inventory.get("healthy_pct"),
            "shelf_visibility_pct": shelf.get("visibility_pct"),
            "open_alerts": alerts.get("open", 0),
            "expiring_soon": expiry.get("expiring_soon", 0),
            "expired": expiry.get("expired", 0),
            "active_visitors": customer_flow.get("active_visitors", 0),
        },
        cameras=cameras,
        inventory=inventory,
        shelf=shelf,
        alerts=alerts,
        expiry=expiry,
        customer_flow=customer_flow,
    )

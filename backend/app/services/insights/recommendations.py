"""Deterministic "recommended action" text builders for Store Intelligence.

Every recommendation is an OPERATIONAL SUGGESTION derived from evidence. The
engine NEVER performs the action itself: it never purchases, never adjusts
inventory, never generates customer-intent claims. The human / existing
workflow decides.

No LLM is used. Every function is deterministic and testable.
"""

from __future__ import annotations

from typing import Optional


def rec_product_stock(name: str, sku: str, *, oos: bool = False) -> str:
    if oos:
        return (
            f"Restock {name} ({sku}) immediately — the store is out of stock. "
            "Place a purchase order / receive stock through the batch intake flow."
        )
    return (
        f"Replenish {name} ({sku}) to bring stock above the reorder level. "
        "Place a purchase order or move backroom stock to the shelf."
    )


def rec_after_expiry_risk(product_name: str, batch_number: Optional[str]) -> str:
    label = batch_number or "this batch"
    return (
        f"Put batch {label} of {product_name} at the front of the shelf "
        "(first-in-first-out) and aim to sell/move it before expiry. "
        "Consider a short-dated goods review with staff."
    )


def rec_after_expired(product_name: str, batch_number: Optional[str]) -> str:
    label = batch_number or "this batch"
    return (
        f"Remove expired batch {label} of {product_name} from the shelf now, "
        "and process a return-to-supplier / disposal record. Do NOT sell."
    )


def rec_stock_rotation(product_name: str) -> str:
    return (
        f"For {product_name}, arrange multi-batch stock so the earliest-expiring "
        "batches sell first — move newer batches to the back. Review the stream "
        "before ordering more."
    )


def rec_low_shelf(shelf_code: str) -> str:
    return (
        f"Shelf {shelf_code} shows low visible occupancy — move backroom stock "
        "forward and tidy the shelf. This is AI-estimated visibility, so confirm "
        "physically before adjusting inventory."
    )


def rec_misplacement(product_name: Optional[str], shelf_code: str) -> str:
    label = product_name or "the detected product"
    return (
        f"Check {label} physically on shelf {shelf_code}: the shelf's planogram "
        "expects different products. Move it to its expected shelf if confirmed."
    )


def rec_high_traffic(zone_name: Optional[str]) -> str:
    return (
        f"Zone '{zone_name}' is a traffic hotspot — consider an end-cap display, "
        "queue/staffing attention, or promotional placement analysis for high "
        "traffic hours."
    )


def rec_high_dwell(zone_name: Optional[str]) -> str:
    return (
        f"Customers spend a long time in zone '{zone_name}'. Review product "
        "searchability/facing on that zone; consider better signage or layout "
        "to convert dwell into purchases (never inferred as intent)."
    )


def rec_high_traffic_low_shelf() -> str:
    return (
        "Replenish shelves in this zone before peak hours: it draws heavy "
        "traffic and now shows low visible stock. Confirm physically and move "
        "backroom stock forward."
    )


def rec_camera(name: Optional[str]) -> str:
    label = name or "The camera"
    return (
        f"{label} is idle/offline. Check power, cable, and pipeline status, "
        "then restart the edge runtime if needed."
    )


def rec_high_selling_low_stock(name: str, sku: str) -> str:
    return (
        f"Restock {name} ({sku}) — it is both selling fast and low on stock. "
        "Prioritize a purchase order / batch intake for this SKU."
    )


def rec_low_stock_low_shelf(name: str, sku: str) -> str:
    return (
        f"Replenish {name} ({sku}): stock is low AND its shelf looks low/empty. "
        "Move backroom stock to the shelf and place an order as needed."
    )


def rec_store_health(state: str) -> str:
    guidance = {
        "HEALTHY": "No action required — keep current routines.",
        "ATTENTION": "Review medium-severity insights and prioritize replenishment / expiry rotation.",
        "CRITICAL": "Take immediate action: restock out-of-stock items, remove expired batches, restore cameras.",
    }
    return guidance.get(state, "Review current insights and take appropriate action.")


def rec_summary_policy() -> str:
    return (
        "Recommended actions are operational suggestions only. They are never "
        "executed automatically and never change inventory on their own."
    )
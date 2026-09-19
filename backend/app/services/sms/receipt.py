"""Bill receipt SMS message builder (M31).

Deterministic plain-text message built ONLY from real persisted data (the
bill row, the store, the customer, and catalogue product names for the line
items). No fabricated totals, no AI-generated copy, no currency guessing —
India's INR is the only supported presentation today (product prices are
Numeric(12,2) and rendered as-is).

Keep it short: a shopkeeper receipt is a few lines, not a marketing essay.
"""

from __future__ import annotations

from typing import Optional, Sequence


def build_bill_receipt(
    bill,
    store,
    customer: Optional[object],
    product_names: Optional[Sequence[str]] = None,
) -> str:
    """Return the receipt SMS body for a persisted bill.

    ``store`` / ``customer`` may be None (display gracefully). Line-item
    product names are passed resolved to keep this function pure (no DB).
    """
    store_name = (getattr(store, "name", None) or "").strip() or "Storeye"
    customer_label = ""
    if customer is not None:
        name = (getattr(customer, "name", None) or "").strip()
        mobile = (getattr(customer, "mobile", None) or "").strip()
        customer_label = f"\nCustomer: {name or mobile}" if (name or mobile) else ""

    created = getattr(bill, "created_at", None)
    date_line = f"\nDate: {created:%d %b %Y %H:%M}" if created is not None else ""

    lines = [
        f"{store_name} — Bill Receipt",
        f"Bill: {getattr(bill, 'bill_number', '')}",
    ]
    if date_line:
        lines.append(date_line.strip())
    if customer_label:
        lines.append(customer_label.strip())

    names = [n for n in (product_names or []) if n]
    if names:
        shown = ", ".join(names[:6])
        if len(names) > 6:
            shown += f" +{len(names) - 6} more"
        lines.append(f"Items: {shown}")

    total = getattr(bill, "total", None)
    lines.append(f"Total paid: \u20b9{total}" if total is not None else "")
    lines.append("Thank you for shopping with us!")

    return "\n".join(line for line in lines if line)
"""Low-stock intelligence.

Determines whether each product is LOW_STOCK using a configurable threshold.
The rule is:
    LOW_STOCK  <=>  available_quantity <= low_stock_threshold
Zero quantity is included (0 <= threshold). No universal threshold is
hard-coded into SQL; callers supply it (defaulting to the app setting).

These are DERIVED insights — the service only reads inventory and returns
structs. It never modifies Inventory rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Inventory, Product

LOW_STOCK = "LOW_STOCK"
OK_STOCK = "OK"


@dataclass
class LowStockInsight:
    """A single product's low-stock status. Derived, not persisted."""

    product_id: UUID
    sku: str
    name: str
    quantity: int
    threshold: int
    status: str  # LOW_STOCK | OK

    @property
    def is_low(self) -> bool:
        return self.status == LOW_STOCK


class InventoryIntelligence:
    def __init__(self, session: Session) -> None:
        self.session = session

    def evaluate(self, store_id: UUID, threshold: Optional[int] = None) -> List[LowStockInsight]:
        """Evaluate low-stock for every product of a store.

        threshold: if None, defaults to app setting LOW_STOCK_THRESHOLD.
        """
        if threshold is None:
            threshold = get_settings().LOW_STOCK_THRESHOLD

        rows = self.session.execute(
            select(Product.id, Product.sku, Product.name, Inventory.quantity)
            .join(Inventory, Inventory.product_id == Product.id)
            .where(Product.store_id == store_id, Inventory.store_id == store_id)
            .order_by(Inventory.quantity.asc())
        ).all()

        return [
            LowStockInsight(
                product_id=r.id,
                sku=r.sku,
                name=r.name,
                quantity=r.quantity,
                threshold=threshold,
                status=LOW_STOCK if r.quantity <= threshold else OK_STOCK,
            )
            for r in rows
        ]

    def low_stock_products(self, store_id: UUID, threshold: Optional[int] = None) -> List[LowStockInsight]:
        return [i for i in self.evaluate(store_id, threshold) if i.is_low]
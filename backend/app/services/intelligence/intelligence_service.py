"""Aggregate inventory-health intelligence for a store.

Composes the low-stock, expiry, and discrepancy services into a single
deterministic store health report. Everything is DERIVED and read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Inventory, Product, ReconciliationResult, REC_REVIEW
from .expiry_intelligence import (
    ExpiryIntelligence,
    EXPIRY_STATUS_EXPIRING_SOON,
    EXPIRY_STATUS_EXPIRED,
    EXPIRY_STATUS_MONTH,
)
from .inventory_intelligence import InventoryIntelligence
from .stock_intelligence import StockDiscrepancyIntelligence


@dataclass
class InventoryHealth:
    """A deterministic health summary for one store. Derived, not persisted."""

    store_id: UUID
    reference_date: date

    # Inventory
    total_products: int
    products_with_stock: int
    low_stock_products: int
    out_of_stock_products: int  # quantity == 0

    # Expiry
    expired_batches: int
    expiring_soon_batches: int  # EXPIRING_SOON (day) + EXPIRY_MONTH (month)

    # Discrepancies
    recent_discrepancies: int
    review_required_reconciliations: int

    low_stock: List = field(default_factory=list)
    expiring_or_expired: List = field(default_factory=list)


class IntelligenceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._inventory = InventoryIntelligence(session)
        self._expiry = ExpiryIntelligence(session)
        self._discrepancy = StockDiscrepancyIntelligence(session)

    def inventory_health(
        self,
        store_id: UUID,
        reference_date: Optional[date] = None,
        low_stock_threshold: Optional[int] = None,
        expiry_warning_days: Optional[int] = None,
        recent_discrepancy_count: int = 5,
    ) -> InventoryHealth:
        """Compute a deterministic health report for a store."""
        if reference_date is None:
            reference_date = datetime.now(timezone.utc).date()
        if low_stock_threshold is None:
            low_stock_threshold = get_settings().LOW_STOCK_THRESHOLD
        if expiry_warning_days is None:
            expiry_warning_days = get_settings().EXPIRY_WARNING_DAYS

        # ---- Inventory aggregates (explicit SQL, deterministic) ----
        total_products = self.session.scalar(
            select(func.count(Product.id)).where(Product.store_id == store_id)
        ) or 0
        products_with_stock = self.session.scalar(
            select(func.count(Inventory.product_id))
            .join(Product, Product.id == Inventory.product_id)
            .where(Inventory.store_id == store_id, Inventory.quantity > 0)
        ) or 0
        out_of_stock = self.session.scalar(
            select(func.count(Inventory.product_id))
            .join(Product, Product.id == Inventory.product_id)
            .where(Inventory.store_id == store_id, Inventory.quantity == 0)
        ) or 0

        low_stock_insights = self._inventory.evaluate(store_id, low_stock_threshold)
        low_stock_count = len([i for i in low_stock_insights if i.is_low])

        # ---- Expiry ----
        expiry_insights = self._expiry.evaluate(store_id, reference_date, expiry_warning_days)
        expired_count = len([i for i in expiry_insights if i.status == EXPIRY_STATUS_EXPIRED])
        expiring_count = len([
            i for i in expiry_insights
            if i.status in (EXPIRY_STATUS_EXPIRING_SOON, EXPIRY_STATUS_MONTH)
        ])

        # ---- Discrepancies ----
        discrepancies = self._discrepancy.results(store_id)
        review_count = len([d for d in discrepancies if d.status == REC_REVIEW])

        return InventoryHealth(
            store_id=store_id,
            reference_date=reference_date,
            total_products=total_products,
            products_with_stock=products_with_stock,
            low_stock_products=low_stock_count,
            out_of_stock_products=out_of_stock,
            expired_batches=expired_count,
            expiring_soon_batches=expiring_count,
            recent_discrepancies=len(discrepancies[:recent_discrepancy_count]),
            review_required_reconciliations=review_count,
            low_stock=low_stock_insights,
            expiring_or_expired=[i for i in expiry_insights if i.status in (
                EXPIRY_STATUS_EXPIRING_SOON, EXPIRY_STATUS_MONTH, EXPIRY_STATUS_EXPIRED
            )],
        )
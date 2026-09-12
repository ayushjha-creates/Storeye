"""Storeye Batch entity.

A Batch represents a manufactured batch of a Product, carrying its own
expiry / manufacturing metadata. It lets inventory be expressed "by batch"
in addition to the aggregate product-level Inventory.

IMPORTANT ARCHITECTURE
    Batch is business/domain data. It is populated through explicit
    application operations (e.g. BatchService.create_batch) using already
    parsed/validated metadata. OCR output is NEVER treated as inventory or
    batch truth automatically.

UNIQUENESS DECISION
    A batch number is NOT globally unique. The same batch number may exist
    for different products and/or different stores. Uniqueness is scoped to
    (store_id, product_id, batch_number).

    NULL batch numbers: PostgreSQL treats NULLs as distinct in a UNIQUE
    constraint, so multiple rows with a NULL batch_number may coexist for
    the same (store_id, product_id). This is intended — a store may receive
    stock without a printed/known batch number, and each such receipt is a
    separate batch row.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

# Mirrors ExpiryParser precision values.
BATCH_PRECISION_DAY = "day"
BATCH_PRECISION_MONTH = "month"


class Batch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "batches"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "product_id", "batch_number",
            name="uq_batches_store_product_number",
        ),
    )

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # batch_number is nullable; see UNIQUENESS DECISION in the module docstring.
    batch_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    manufacturing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Preserve the parser's precision distinction ("day" | "month"); a month-
    # precision expiry is stored as the 1st of the month but flagged as month.
    expiry_date_precision: Mapped[str] = mapped_column(String(10), default=BATCH_PRECISION_DAY)
    mrp: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    # Batch-level quantity (in addition to aggregate Inventory.quantity).
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    store = relationship("Store")
    product = relationship("Product")
    movements = relationship(
        "InventoryMovement", back_populates="batch", passive_deletes=True
    )
"""Storeye Product entity.

`ai_classes` lists the Edge AI class names (from the shelf/product detector,
e.g. "Complan", "Glucon-D") that EXPLICITLY map to this Storeye product. The
mapping is a deliberate, configurable association — the AI never guesses it.
A product with an empty/missing list stays "unmapped": product observations
that carry a class with no mapping are surfaced as "Unmapped AI class" rather
than silently attached to a product.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        # SKU unique within a store
        UniqueConstraint("store_id", "sku", name="uq_products_store_sku"),
        # Barcode (GTIN/EAN/UPC/etc.) unique within a store. NULLs are allowed
        # and remain distinct, so unmapped products are fine.
        UniqueConstraint("store_id", "barcode", name="uq_products_store_barcode"),
    )

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Machine-readable product identifier printed on the package. Resolved by
    # close-up Smart Batch Receiving; never parsed for expiry/batch data.
    barcode: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    unit: Mapped[str] = mapped_column(String(30), default="unit")  # unit|kg|litre|pack
    selling_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    cost_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Explicit AI class-name -> product mapping (JSONB list of strings).
    # See module docstring. No default mapping is ever invented.
    ai_classes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    store = relationship("Store", back_populates="products")
    inventories = relationship("Inventory", back_populates="product", cascade="all, delete-orphan")
    batches = relationship("Batch", back_populates="product", cascade="all, delete-orphan")
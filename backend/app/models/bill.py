"""Storeye Bill and BillItem entities.

A bill is a persistent, manually-created billing artifact for paperless
billing. Billing is MANUAL: the shopkeeper selects products/quantities;
there is NO camera/AI billing. SMS receipt delivery (M31) is queued in the
`sms_messages` outbox and never mutates the bill itself.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Bill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bills"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bill_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    sale_id = mapped_column(
        ForeignKey("sales.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    delivery_status: Mapped[str] = mapped_column(String(30), default="DRAFT")  # DRAFT|SENT|DELIVERED|FAILED

    items = relationship("BillItem", back_populates="bill", cascade="all, delete-orphan")


class BillItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "bill_items"

    bill_id = mapped_column(
        ForeignKey("bills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    bill = relationship("Bill", back_populates="items")
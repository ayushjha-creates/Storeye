"""Storeye Customer entity.

Minimal personal data for digital billing. Only necessary fields.
SMS bill-receipt delivery (M31) queues against `mobile` at bill time.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("store_id", "mobile", name="uq_customers_store_mobile"),
    )

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mobile: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    store = relationship("Store", back_populates="customers")
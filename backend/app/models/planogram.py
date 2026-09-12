"""Storeye Planogram and PlanogramItem entities.

A planogram defines the intended product layout across shelves. This
milestone only establishes the data model; automatic compliance checks
belong to a later milestone.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Planogram(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "planograms"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    items = relationship("PlanogramItem", back_populates="planogram", cascade="all, delete-orphan")


class PlanogramItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "planogram_items"

    planogram_id = mapped_column(
        ForeignKey("planograms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shelf_id = mapped_column(
        ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expected_facings: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    minimum_facings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    maximum_facings: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    planogram = relationship("Planogram", back_populates="items")
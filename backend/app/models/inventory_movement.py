"""Storeye InventoryMovement entity.

Append-only history of inventory quantity changes. Historical changes are
never silently overwritten.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class InventoryMovement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "inventory_movements"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Optional reference to the specific batch this movement belongs to.
    # ondelete=SET NULL so historical movements survive batch deletion.
    batch_id = mapped_column(
        ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity_change: Mapped[int] = mapped_column(Integer, nullable=False)  # +/-
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)  # PURCHASE|SALE|RETURN|ADJUSTMENT|DAMAGE|EXPIRY|TRANSFER
    reference: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # e.g. bill no
    timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    batch = relationship("Batch", back_populates="movements")
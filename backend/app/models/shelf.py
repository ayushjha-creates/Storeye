"""Storeye Shelf entity.

Represents a real physical shelf, identified by a stable label such as
A1, A2, B1. A shelf belongs to a zone. It is NOT tied to a camera
detection; vision reconciliation happens later.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Shelf(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shelves"
    __table_args__ = (
        # stable identifier unique per store
        UniqueConstraint("store_id", "code", name="uq_shelves_store_code"),
    )

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id = mapped_column(
        ForeignKey("zones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)  # e.g. A1, A2, B1
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    zone = relationship("Zone", back_populates="shelves")
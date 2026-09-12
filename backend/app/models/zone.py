"""Storeye Zone entity.

A physical area of the store (e.g. entrance, queue, an aisle group, or a
region). A Shelf belongs to a zone. This represents real store layout, not
a camera ROI.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Zone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zones"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    store = relationship("Store", back_populates="zones")
    shelves = relationship("Shelf", back_populates="zone")
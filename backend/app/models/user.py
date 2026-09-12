"""Storeye User entity (staff)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    # Role values kept as plain strings; authorization logic lives at the
    # service/API layer, not hard-coded here.
    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(50), default="ASSOCIATE")

    store = relationship("Store", back_populates="users")
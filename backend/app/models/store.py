"""Storeye Store entity."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Store(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stores"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    # M21: explicit, stable demo-store marker. Scenario/demo operations are
    # refused unless this is True, so real stores can never be modified by
    # demo tooling even if a store name is spoofed.
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )

    users = relationship("User", back_populates="store", passive_deletes=True)
    cameras = relationship("Camera", back_populates="store", passive_deletes=True)
    zones = relationship("Zone", back_populates="store", passive_deletes=True)
    products = relationship("Product", back_populates="store", passive_deletes=True)
    customers = relationship("Customer", back_populates="store", passive_deletes=True)
"""Storeye Store entity."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Store(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stores"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")

    users = relationship("User", back_populates="store", passive_deletes=True)
    cameras = relationship("Camera", back_populates="store", passive_deletes=True)
    zones = relationship("Zone", back_populates="store", passive_deletes=True)
    products = relationship("Product", back_populates="store", passive_deletes=True)
    customers = relationship("Customer", back_populates="store", passive_deletes=True)
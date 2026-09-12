"""Storeye Notification entity.

A basic structure for future alerts (EXPIRY, LOW_STOCK, SHELF_GAP,
SYSTEM). Delivery (websocket/push/in-app) is a later milestone.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notif_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # EXPIRY|LOW_STOCK|SHELF_GAP|SYSTEM
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="INFO")  # INFO|WARNING|CRITICAL
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
"""Storeye Camera entity.

Represents a physical/configured camera device. Raw video is never
stored in PostgreSQL. Live streaming is handled elsewhere (a later
milestone); this only captures configuration metadata.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Camera(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cameras"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    camera_type: Mapped[str] = mapped_column(String(50), default="usb")  # usb|rtsp|file
    is_active: Mapped[bool] = mapped_column(default=True)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    store = relationship("Store", back_populates="cameras")
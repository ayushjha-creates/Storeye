"""Storeye User entity (staff).

Each user belongs to exactly one store (`store_id`). Authentication fields
(`email`, `password_hash`, `is_active`, `last_login_at`) are additive on top of
the original M11 model so existing deployments upgrade cleanly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    # Role values kept as plain strings; authorization logic lives at the
    # service/API layer (app.core.auth / app.api.authz), not hard-coded here.
    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    mobile: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(50), default="ASSOCIATE")

    # --- Authentication (added by the authentication milestone) -------------
    # Login identity. NULL rows cannot authenticate until provisioned with an
    # email + password (uniqueness ignores NULLs, so legacy rows are safe).
    email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    # Argon2id encoded hash (never a plaintext password; never returned by APIs).
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ------------------------------------------------------------------------

    store = relationship("Store", back_populates="users")
    sessions = relationship("AuthSession", back_populates="user")
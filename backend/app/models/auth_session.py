"""Server-side authentication session.

Session records never store the raw session secret. Only a SHA-256 hash of the
secret is persisted; the raw secret lives solely in the HttpOnly cookie issued
to the browser. This limits a database leak to impersonation-by-hash-cracking,
never direct credential disclosure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class AuthSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    # SHA-256 hex digest of the raw session secret. Unique + indexed.
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    user_id = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Optional metadata about the client that created the session.
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    user = relationship("User", back_populates="sessions")
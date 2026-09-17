"""Demo scenario state (M21).

One row per demo store recording which deterministic scenario is active and
when the baseline was last reset. This is the ONLY M21 table: scenario data
itself lives in the normal business tables (inventory, batches, observations,
zone visits, ...) so a browser refresh always reflects database truth — never
frontend-only state.

Isolation: `store_id` points at a store whose `Store.is_demo` is True. The
DemoScenarioEngine refuses to operate on any other store.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DemoScenarioState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "demo_scenario_state"

    store_id: Mapped[UUID] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    active_key: Mapped[str] = mapped_column(String(40), nullable=False, default="NORMAL_STORE")
    last_reset_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    store = relationship("Store")

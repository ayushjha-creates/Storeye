"""Baseline reset for the demo store (M21).

M21 never mutates production data: the baseline is rebuilt with the M18 demo
seed (which already sets `Store.is_demo = True`) and every scenario is an
overlay on top of it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from scripts.seed_demo import reset_demo_store, seed_with_session


def reset_to_baseline(session: Session, now: Optional[datetime] = None) -> dict:
    """Delete the demo store's data and re-seed the deterministic baseline.

    Safety: `reset_demo_store` only ever removes the demo store (resolved by
    its stable id / name) plus its children. No other store is touched.
    """
    reset_demo_store(session)
    return seed_with_session(session, now=now)

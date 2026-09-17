"""Baseline reset for the demo store (M21, extended by M25).

M21 never mutates production data: the baseline is rebuilt with the M18 demo
seed (which already sets `Store.is_demo = True`) and every scenario is an
overlay on top of it.

M25 adds ONE extra guarantee: demo-reset (and therefore every scenario
activation, which starts from the baseline) also clears the demo-generated
USB-intake state (jobs + on-disk files) so repeatable demo presentations never
show stale mobile-intake candidates. Real (non-demo) intake files, model
assets and the production store are never touched.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from scripts.seed_demo import reset_demo_store, seed_with_session

logger = logging.getLogger("storeye.demo")


def _reset_mobile_intake_demo_state() -> dict:
    """Best-effort: clear demo-generated USB-intake jobs/files.

    Skipped while running under pytest (tests install their own ephemeral
    intake services) and never raises: a failure here must not block a demo
    reset. Uses the real intake manager so the SAME index the watcher writes
    to is cleaned.
    """
    if "pytest" in sys.modules:
        return {"skipped": "pytest"}
    try:
        from ..mobile_intake.manager import get_intake_manager

        service = get_intake_manager()
        return service.reset_demo_state()
    except Exception:  # pragma: no cover - defensive
        logger.exception("Best-effort mobile-intake demo cleanup failed")
        return {"skipped": "error"}


def reset_to_baseline(session: Session, now: Optional[datetime] = None) -> dict:
    """Delete the demo store's data and re-seed the deterministic baseline.

    Safety: `reset_demo_store` only ever removes the demo store (resolved by
    its stable id / name) plus its children. No other store is touched.
    """
    result = {}
    reset_demo_store(session)
    result = seed_with_session(session, now=now)
    result["intake_demo_cleanup"] = _reset_mobile_intake_demo_state()
    return result
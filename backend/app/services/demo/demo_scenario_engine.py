"""Demo scenario engine (M21).

Deterministic orchestration for the Storeye presentation environment:

    reset baseline -> apply scenario overlay -> evaluate M20 insights
                   -> sync M16 alerts -> persist active scenario

The engine NEVER touches a non-demo store: it resolves the demo store by its
stable id and refuses to proceed unless `Store.is_demo` is True. This guard is
in the service layer, so it holds even if a caller bypasses the HTTP layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DemoScenarioState, Store
from app.services.insights import InsightEngine
from scripts.seed_demo import DEMO_STORE_ID, DEMO_STORE_NAME

from . import demo_data as data
from .demo_reset import reset_to_baseline
from .demo_scenarios import APPLIERS


class DemoStoreNotFound(Exception):
    """The demo store does not exist (and could not be created)."""


class NotADemoStore(Exception):
    """A guard refused to operate because the target is not a demo store."""


class UnknownScenario(Exception):
    """The requested scenario key is not in the catalog."""


class DemoScenarioEngine:
    def __init__(self, session: Session, demo_store_id: Optional[UUID] = None) -> None:
        self.session = session
        self.demo_store_id = demo_store_id or DEMO_STORE_ID

    # ------------------------------------------------------------------
    # catalog
    # ------------------------------------------------------------------
    def list_scenarios(self) -> List[data.ScenarioInfo]:
        return list(data.SCENARIOS)

    def get_scenario(self, key: str) -> data.ScenarioInfo:
        info = data.SCENARIOS_BY_KEY.get(key)
        if info is None:
            raise UnknownScenario(key)
        return info

    # ------------------------------------------------------------------
    # demo-store resolution + isolation guard
    # ------------------------------------------------------------------
    def _resolve_store(self, *, create: bool = False) -> Optional[Store]:
        store = self.session.get(Store, self.demo_store_id)
        if store is None and create:
            reset_to_baseline(self.session)
            self.session.expire_all()
            store = self.session.get(Store, self.demo_store_id)
        return store

    def _fresh_store(self) -> Optional[Store]:
        """Re-read the demo store after a reset (identity map may be stale)."""
        self.session.expire_all()
        return self.session.get(Store, self.demo_store_id)

    def _require_demo_store(self, *, create: bool = False) -> Store:
        store = self._resolve_store(create=create)
        if store is None:
            raise DemoStoreNotFound(
                f"Demo store '{DEMO_STORE_NAME}' not found. Seed it first."
            )
        if not store.is_demo:
            raise NotADemoStore(
                "Refusing to run demo operations on a non-demo store "
                "(Store.is_demo is not True)."
            )
        return store

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, object]:
        store = self._resolve_store(create=False)
        out: Dict[str, object] = {
            "demo_store": DEMO_STORE_NAME,
            "demo_store_id": str(self.demo_store_id),
            "store_exists": store is not None,
            "scenario": None,
            "active_key": None,
            "last_reset_at": None,
            "last_activated_at": None,
        }
        if store is None:
            return out
        out["store_exists"] = True
        out["store_is_demo"] = bool(store.is_demo)
        state = self.session.scalars(
            select(DemoScenarioState).where(DemoScenarioState.store_id == store.id)
        ).first()
        key = state.active_key if state is not None else data.DEFAULT_SCENARIO
        out["active_key"] = key
        info = data.SCENARIOS_BY_KEY.get(key)
        if info is not None:
            out["scenario"] = {
                "key": info.key,
                "name": info.name,
                "description": info.description,
                "category": info.category,
            }
        if state is not None:
            out["last_reset_at"] = state.last_reset_at
            out["last_activated_at"] = state.last_activated_at
        return out

    # ------------------------------------------------------------------
    # activation
    # ------------------------------------------------------------------
    def _set_state(
        self,
        store: Store,
        key: str,
        now: datetime,
        *,
        reset_at: Optional[datetime] = None,
    ) -> DemoScenarioState:
        state = self.session.scalars(
            select(DemoScenarioState).where(DemoScenarioState.store_id == store.id)
        ).first()
        if state is None:
            state = DemoScenarioState(store_id=store.id)
            self.session.add(state)
        state.active_key = key
        state.last_activated_at = now
        state.last_reset_at = reset_at or now
        self.session.flush()
        return state

    def activate(
        self, key: str, *, now: Optional[datetime] = None
    ) -> Dict[str, object]:
        info = self.get_scenario(key)
        now = now or datetime.now(timezone.utc)

        store = self._require_demo_store(create=True)

        # 1) known baseline (separately committed by the seeder).
        reset_to_baseline(self.session, now=now)
        store = self._fresh_store()
        if store is None or not store.is_demo:
            raise NotADemoStore(
                "Refusing to run demo operations on a non-demo store "
                "(Store.is_demo is not True)."
            )

        # 2) deterministic overlay + 3) evaluate derived intelligence.
        try:
            metrics = APPLIERS[info.key](self.session, store, now)
            self.session.flush()
            # evaluate() persists rule insights, the cached STORE_HEALTH
            # summary and M16 alert sync in one atomic reconcile.
            evaluation = InsightEngine(self.session).evaluate(
                store.id, now=now, reference_date=now.date()
            )
        except Exception:
            self.session.rollback()
            # Best-effort restore so the presenter is never left with a
            # half-modified demo store.
            reset_to_baseline(self.session, now=now)
            store = self._fresh_store()
            if store is not None:
                self._set_state(store, data.DEFAULT_SCENARIO, now)
            self.session.commit()
            raise

        self._set_state(store, info.key, now)
        self.session.commit()

        return {
            "ok": True,
            "active_key": info.key,
            "scenario": {
                "key": info.key,
                "name": info.name,
                "description": info.description,
                "category": info.category,
                "expected": info.expected,
                "focus_path": info.focus_path,
            },
            "store": {"id": str(store.id), "name": store.name},
            "metrics": metrics,
            "evaluation": {
                "candidates": evaluation.candidates,
                "created": evaluation.created,
                "refreshed": evaluation.refreshed,
                "resolved": evaluation.resolved,
                "expired": evaluation.expired,
                "alerts_created": evaluation.alerts_created,
                "alerts_updated": evaluation.alerts_updated,
            },
            "activated_at": now,
        }

    def reset(self, *, now: Optional[datetime] = None) -> Dict[str, object]:
        """Reset the demo store to the healthy NORMAL_STORE baseline."""
        return self.activate(data.DEFAULT_SCENARIO, now=now)

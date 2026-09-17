"""Demo Showcase Mode routes (M18 baseline, extended by M21).

Read-only catalog/status endpoints are open in demo mode. Mutating endpoints
(reset / scenario activation) require the `X-Demo-Reset-Key` header and only
ever touch the demo store. The demo store is resolved by its stable id and
must have `Store.is_demo is True`; any other store is refused in the service
layer, not just the HTTP layer.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...schemas import (
    DemoActivationResult,
    DemoScenarioList,
    DemoScenarioRead,
    DemoStatusRead,
)
from ...services.demo import (
    DemoScenarioEngine,
    DemoStoreNotFound,
    NotADemoStore,
    UnknownScenario,
)
from ..deps import get_db

router = APIRouter(prefix="/demo", tags=["demo"])

DEFAULT_RESET_KEY = "storeye-demo-reset"


def _demo_mode() -> bool:
    return bool(get_settings().DEMO_MODE)


def _require_demo_mode() -> None:
    if not _demo_mode():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo mode is disabled on this deployment.",
        )


def _require_reset_key(x_demo_reset_key: str) -> None:
    expected = os.environ.get("DEMO_RESET_KEY") or get_settings().DEMO_RESET_KEY or DEFAULT_RESET_KEY
    if not expected or x_demo_reset_key != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Demo-Reset-Key header.",
        )


def _engine(db: Session) -> DemoScenarioEngine:
    return DemoScenarioEngine(db)


# ---------------------------------------------------------------------------
# read endpoints
# ---------------------------------------------------------------------------


@router.get("/scenarios", response_model=DemoScenarioList)
def list_scenarios(db: Session = Depends(get_db)) -> DemoScenarioList:
    _require_demo_mode()
    engine = _engine(db)
    state = engine.status()
    active_key = state.get("active_key")
    return DemoScenarioList(
        demo_mode=_demo_mode(),
        demo_store=str(state["demo_store"]),
        store_exists=bool(state["store_exists"]),
        store_is_demo=bool(state.get("store_is_demo", False)),
        active_key=active_key if isinstance(active_key, str) else None,
        scenarios=[
            DemoScenarioRead.from_info(info, active=info.key == active_key)
            for info in engine.list_scenarios()
        ],
    )


@router.get("/scenarios/{key}", response_model=DemoScenarioRead)
def get_scenario(key: str, db: Session = Depends(get_db)) -> DemoScenarioRead:
    _require_demo_mode()
    engine = _engine(db)
    try:
        info = engine.get_scenario(key)
    except UnknownScenario:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {key}")
    active_key = engine.status().get("active_key")
    return DemoScenarioRead.from_info(info, active=info.key == active_key)


@router.get("/status", response_model=DemoStatusRead)
def demo_status(db: Session = Depends(get_db)) -> DemoStatusRead:
    _require_demo_mode()
    engine = _engine(db)
    state = engine.status()
    return DemoStatusRead(
        demo_mode=_demo_mode(),
        demo_store=str(state["demo_store"]),
        demo_store_id=state["demo_store_id"],
        store_exists=bool(state["store_exists"]),
        store_is_demo=bool(state.get("store_is_demo", False)),
        active_key=state.get("active_key"),
        scenario=state.get("scenario"),
        last_reset_at=state.get("last_reset_at"),
        last_activated_at=state.get("last_activated_at"),
    )


# ---------------------------------------------------------------------------
# mutating endpoints (guarded)
# ---------------------------------------------------------------------------


@router.post("/scenarios/{key}/activate", response_model=DemoActivationResult)
def activate_scenario(
    key: str,
    db: Session = Depends(get_db),
    x_demo_reset_key: str = Header(default="", alias="X-Demo-Reset-Key"),
) -> DemoActivationResult:
    _require_demo_mode()
    _require_reset_key(x_demo_reset_key)
    engine = _engine(db)
    try:
        payload = engine.activate(key)
    except UnknownScenario:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {key}")
    except DemoStoreNotFound as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except NotADemoStore as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return DemoActivationResult.from_engine(payload)


@router.post("/reset", response_model=DemoActivationResult)
def reset_demo(
    db: Session = Depends(get_db),
    x_demo_reset_key: str = Header(default="", alias="X-Demo-Reset-Key"),
) -> DemoActivationResult:
    _require_demo_mode()
    _require_reset_key(x_demo_reset_key)
    engine = _engine(db)
    try:
        payload = engine.reset()
    except DemoStoreNotFound as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except NotADemoStore as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return DemoActivationResult.from_engine(payload)

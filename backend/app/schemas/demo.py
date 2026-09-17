"""Pydantic schemas for the M21 Demo & Scenario Engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ..services.demo import ScenarioInfo


class DemoScenarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    description: str
    category: str
    expected: list[str] = []
    focus_path: str
    active: bool = False

    @classmethod
    def from_info(cls, info: ScenarioInfo, *, active: bool = False) -> "DemoScenarioRead":
        return cls(
            key=info.key,
            name=info.name,
            description=info.description,
            category=info.category,
            expected=list(info.expected),
            focus_path=info.focus_path,
            active=active,
        )


class DemoScenarioList(BaseModel):
    demo_mode: bool
    demo_store: str
    store_exists: bool
    store_is_demo: bool = False
    active_key: Optional[str] = None
    scenarios: list[DemoScenarioRead]


class DemoStatusRead(BaseModel):
    demo_mode: bool
    demo_store: str
    demo_store_id: UUID
    store_exists: bool
    store_is_demo: bool = False
    active_key: Optional[str] = None
    scenario: Optional[dict[str, Any]] = None
    last_reset_at: Optional[datetime] = None
    last_activated_at: Optional[datetime] = None


class DemoActivationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    active_key: str
    scenario: dict[str, Any]
    store: dict[str, Any]
    metrics: dict[str, Any] = {}
    evaluation: dict[str, Any] = {}
    activated_at: datetime
    # M25: only present when a demo package was queued into the USB intake.
    mobile_intake_demo: Optional[dict[str, Any]] = None

    @classmethod
    def from_engine(cls, payload: dict[str, Any]) -> "DemoActivationResult":
        return cls(**payload)

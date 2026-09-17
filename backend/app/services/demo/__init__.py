"""Storeye Demo & Scenario Engine (M21).

Deterministic presentation environment built on the real backend: a scenario
activation resets the demo store to the M18 baseline, applies a deterministic
overlay, then runs the REAL M20 InsightEngine and M16 alert sync.

Guarantees:
    * only the demo store (`Store.is_demo is True`) is ever modified,
    * no cloud/LLM/third-party dependency; everything runs on the local stack,
    * scenarios live in the database (never frontend-only state), so a browser
      refresh always shows the active scenario,
    * M15/M16/M17/M19/M20 behaviour is reused, not duplicated.
"""

from .demo_data import (
    DEFAULT_SCENARIO,
    SCENARIOS,
    SCENARIOS_BY_KEY,
    VALID_SCENARIO_KEYS,
    ScenarioInfo,
)
from .demo_reset import reset_to_baseline
from .demo_scenario_engine import (
    DemoScenarioEngine,
    DemoStoreNotFound,
    NotADemoStore,
    UnknownScenario,
)

__all__ = [
    "DemoScenarioEngine",
    "DemoStoreNotFound",
    "NotADemoStore",
    "UnknownScenario",
    "reset_to_baseline",
    "ScenarioInfo",
    "SCENARIOS",
    "SCENARIOS_BY_KEY",
    "VALID_SCENARIO_KEYS",
    "DEFAULT_SCENARIO",
]

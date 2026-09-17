"""M20 Store Intelligence & Actionable Business Insights.

Deterministic, rule-based insight engine that consumes EXISTING persisted data
(inventory, batches, shelf/product intelligence, alerts, anonymous journeys)
and produces evidence-backed operational insights with recommended actions.

This engine is NOT an alert system. Insights persist as a separate layer
carrying evidence, provenance and recommended actions so the "why" is never
lost. At configurable actionable severity, an insight may additionally
create/refresh an M16 alert via the standard AlertService deduplication — it
never spawns a second alert system.

Nothing in this package runs a new CV pipeline, generates customer-intent
claims, or mutates inventory, batches, sales or bills. Privacy rules
(crops, embeddings, identities) from M19 remain fully in force.
"""

from .insight_engine import InsightEngine, InsightEvalResult
from .insight_rules import RuleContext
from .insight_types import TYPE_CATEGORY, TYPE_DEFAULT_SEVERITY, RuleCandidate
from .store_health import StoreHealth, StoreHealthService, VALID_STORE_HEALTH_STATES

__all__ = [
    "InsightEngine",
    "InsightEvalResult",
    "RuleContext",
    "RuleCandidate",
    "TYPE_CATEGORY",
    "TYPE_DEFAULT_SEVERITY",
    "StoreHealth",
    "StoreHealthService",
    "VALID_STORE_HEALTH_STATES",
]
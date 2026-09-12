"""Storeye alert layer (M16).

Alerts are INFORMATIONAL / ACTIONABLE notifications derived from EXISTING
intelligence results. The layer never runs camera inference and never mutates
inventory/batches/bills/sales — its only persistence effect is `alerts` rows.

Modules:
    alert_service   create (with deterministic deduplication), query, lifecycle
                    transitions (OPEN -> ACKNOWLEDGED -> RESOLVED, DISMISSED)
    alert_rules     AlertRuleEngine — evaluate existing product/shelf/expiry/
                    reconciliation intelligence and upsert alerts
    errors          alert-layer domain exceptions
"""

from .errors import (
    EntityNotFoundError,
    InvalidStatusTransitionError,
    StoreyeAlertError,
    ValidationError,
)
from .alert_service import AlertService
from .alert_rules import AlertRuleEngine, AlertRuleResult

__all__ = [
    "StoreyeAlertError",
    "ValidationError",
    "InvalidStatusTransitionError",
    "EntityNotFoundError",
    "AlertService",
    "AlertRuleEngine",
    "AlertRuleResult",
]
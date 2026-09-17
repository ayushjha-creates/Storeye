"""M23 deployment tooling (read-only diagnostics).

* ``app.deployment.model_check`` — validate local AI model assets.
* ``app.deployment.doctor``       — full environment readiness check.
* ``app.deployment.report``       — shared PASS/WARN/ERROR result model.

These modules never mutate business data and never download anything.
"""

from __future__ import annotations

from .report import Check, CheckReport, Status

__all__ = ["Check", "CheckReport", "Status"]

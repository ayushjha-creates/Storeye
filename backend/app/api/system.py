"""M22 system readiness/status API.

Distinguishes clearly:

    application alive      -> /api/health
    business DB ready      -> /api/readyz (this router; PostgreSQL + Alembic)
    AI runtime / cameras   -> /api/edge/status
    demo configuration     -> /api/demo/status

The legacy `/api/health`, `/api/ready`, `/api/metrics` endpoints are retained
unchanged for backward compatibility (they report the legacy SQLite diagnostics
stack). This router is the authoritative business-readiness view.
"""

from __future__ import annotations

from fastapi import APIRouter, status as http_status
from fastapi.responses import JSONResponse

from ..core.config import get_settings
from ..core.startup import assess_runtime

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
def system_status():
    """Detailed, non-mutating readiness report for the edge deployment."""
    settings = get_settings()
    report = assess_runtime(skip_in_tests=False)

    if not report.config_ok:
        overall = "ERROR"
    elif not report.database_configured:
        overall = "DEGRADED"
    elif not report.database_reachable:
        overall = "ERROR"
    elif report.migration_current is False:
        overall = "DEGRADED"
    else:
        overall = "OK"

    payload = {
        "status": overall,
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "strict_startup": settings.is_strict,
        "database": {
            "authoritative": "postgresql",
            "configured": report.database_configured,
            "reachable": report.database_reachable,
            "migration_current": report.migration_current,
            "migration_db_revision": report.migration_db_revision,
            "migration_head": report.migration_head,
        },
        "reid": {
            "enabled": report.reid_enabled,
            "provider": settings.REID_PROVIDER if report.reid_enabled else None,
        },
        "demo_mode": bool(settings.DEMO_MODE),
        "notices": report.messages,
    }
    code = http_status.HTTP_200_OK if overall in {"OK", "DEGRADED"} else http_status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=payload)

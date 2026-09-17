"""Application-level manager for the mobile-intake bridge (M25).

Owns the process-wide ``MobileIntakeService`` singleton, wiring it to the
settings and to the real M17 scan pipeline (a DB-backed
``BatchIntakeService``). Under pytest the tests replace the global instance
with an ephemeral service (temp intake root + fake scanner); the router only
ever talks to ``get_intake_manager()``.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from .intake_service import MobileIntakeService

logger = logging.getLogger("storeye.mobile_intake")

_global_service: Optional[MobileIntakeService] = None
_global_lock = threading.Lock()


def _default_scanner(image_bytes: bytes) -> object:
    """Run the existing M17 read-only scan over the pushed photo bytes."""
    from ..batch_intake.batch_intake_service import BatchIntakeService
    from ...db.session import get_session

    session = get_session()
    try:
        return BatchIntakeService(session).scan_package(image_bytes, store_id=None)
    finally:
        session.close()


def _build_service() -> MobileIntakeService:
    from ...core.config import get_settings

    settings = get_settings()
    return MobileIntakeService(
        root=settings.INTAKE_ROOT,
        scanner=_default_scanner,
        watch_interval_sec=settings.INTAKE_WATCH_INTERVAL_SECONDS,
        stability_sec=settings.INTAKE_STABILITY_SECONDS,
        max_file_bytes=settings.INTAKE_MAX_MB * 1024 * 1024,
        retention_days=settings.INTAKE_RETENTION_DAYS,
    )


def get_intake_manager() -> MobileIntakeService:
    """Return the process-wide intake service (creating it lazily)."""
    global _global_service
    with _global_lock:
        if _global_service is None:
            _global_service = _build_service()
            _global_service.ensure_dirs()
            _global_service.load_index()
        return _global_service


def configure_intake_manager(service: MobileIntakeService) -> None:
    """Install a test/ephemeral service (tests only)."""
    global _global_service
    with _global_lock:
        _global_service = service


def reset_intake_manager() -> None:
    """Stop and forget the global service (tests only)."""
    global _global_service
    with _global_lock:
        if _global_service is not None:
            try:
                _global_service.stop(timeout=1.0)
            except Exception:
                pass
        _global_service = None
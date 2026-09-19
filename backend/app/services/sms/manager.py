"""Process-wide SMS worker (M31).

A single daemon background thread drains the ``sms_messages`` outbox every
``SMS_POLL_SECONDS``. Each tick opens a FRESH database session (it never shares
the request/edge sessions), claims the next batch, and delivers through the
MSG91 gateway. Under pytest the global worker is replaced with an ephemeral one
or never started; tests drive delivery deterministically via ``drain_once()``.

Mirrors the M25 intake-watcher manager pattern exactly.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .gateway import get_gateway

logger = logging.getLogger("storeye.sms")


class SmsWorker(threading.Thread):
    """Daemon thread that drains the outbox on a fixed poll cadence."""

    def __init__(
        self,
        poll_seconds: float = 5.0,
        gateway=None,
        sleep_fn=time.sleep,
    ) -> None:
        super().__init__(name="storeye-sms-worker", daemon=True)
        self._poll = max(float(poll_seconds), 0.1)
        self._gateway = gateway  # None -> built lazily per tick from settings
        self._sleep = sleep_fn
        self._stop = threading.Event()
        self.ticked = 0
        self.last_result: Optional[dict] = None
        self._lock = threading.Lock()

    def drain_once(self, limit: int = 20) -> dict:
        """Claim + send one batch over a fresh session (also used by tests/CLI)."""
        from ...db.session import get_session
        from .outbox import SmsOutboxService

        session = get_session()
        try:
            service = SmsOutboxService(session)
            return service.process_pending(limit=limit, gateway=self._gateway)
        finally:
            session.close()

    def run(self) -> None:
        logger.info("SMS worker started (poll every %ss)", self._poll)
        while not self._stop.wait(self._poll):
            try:
                self.last_result = self.drain_once()
                with self._lock:
                    self.ticked += 1
            except Exception:  # pragma: no cover - defensive
                logger.exception("SMS worker tick failed")
        logger.info("SMS worker stopped")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.join(timeout)


_global_worker: Optional[SmsWorker] = None
_global_lock = threading.Lock()


def _build_worker() -> SmsWorker:
    from ...core.config import get_settings

    settings = get_settings()
    return SmsWorker(
        poll_seconds=settings.SMS_POLL_SECONDS,
        gateway=get_gateway(settings),
    )


def get_sms_worker() -> Optional[SmsWorker]:
    """Return the process-wide worker, or None while SMS is disabled."""
    global _global_worker
    with _global_lock:
        if _global_worker is None:
            from ...core.config import get_settings

            if not get_settings().SMS_ENABLED:
                return None
            _global_worker = _build_worker()
        return _global_worker


def start_sms_worker() -> Optional[SmsWorker]:
    worker = get_sms_worker()
    if worker is not None and not worker.is_alive():
        worker.start()
    return worker


def stop_sms_worker(timeout: float = 5.0) -> None:
    global _global_worker
    with _global_lock:
        if _global_worker is not None:
            try:
                _global_worker.stop(timeout=timeout)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Error stopping SMS worker")
        _global_worker = None


def configure_sms_worker(worker: Optional[SmsWorker]) -> None:
    """Install or replace the global worker (tests only)."""
    global _global_worker
    with _global_lock:
        _global_worker = worker


def reset_sms_worker() -> None:
    """Stop and forget the global worker (tests only)."""
    global _global_worker
    with _global_lock:
        if _global_worker is not None:
            try:
                _global_worker.stop(timeout=1.0)
            except Exception:
                pass
        _global_worker = None
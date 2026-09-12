"""Process-wide Edge runtime singleton registry.

The FastAPI app and the edge control API share ONE EdgeRuntime instance for the
process so start/stop/status are globally consistent and threads are not
spawned per request.
"""

from __future__ import annotations

import threading
from typing import Optional

from .runtime import EdgeRuntime

_lock = threading.Lock()
_runtime: Optional[EdgeRuntime] = None


def get_runtime() -> EdgeRuntime:
    """Return the process-wide EdgeRuntime, creating it lazily."""
    global _runtime
    if _runtime is None:
        with _lock:
            if _runtime is None:
                _runtime = EdgeRuntime()
    return _runtime


def set_runtime(runtime: EdgeRuntime) -> None:
    """Install a runtime (used by tests to inject fakes)."""
    global _runtime
    with _lock:
        _runtime = runtime

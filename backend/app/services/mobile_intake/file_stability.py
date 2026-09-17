"""Copy-completion detection (M25).

A phone typically copies a file in several chunks. Reading a partially-copied
picture must never happen, so we wait until the file size has been unchanged
for a stability window before touching the bytes. Handles the most common
case (the file simply stops growing).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("storeye.mobile_intake")


def wait_until_stable(
    path: Path,
    *,
    interval: float = 1.0,
    stability_sec: float = 2.0,
    max_wait_sec: float = 60.0,
    sleep_fn=time.sleep,
) -> bool:
    """Return whether ``path`` is a settled file (size unchanged for a while).

    Returns ``False`` if the file never stabilised (it kept growing/vanishing)
    inside ``max_wait_sec`` — the caller must then treat the copy as failed.
    """
    started = time.monotonic()
    last_size: Optional[int] = None
    changed_at = started

    while True:
        elapsed = time.monotonic() - started
        try:
            size = path.stat().st_size
        except OSError:
            size = None

        if size != last_size:
            last_size = size
            changed_at = time.monotonic()
            if size == 0:
                changed_at = time.monotonic()
        elif size is not None and (time.monotonic() - changed_at) >= stability_sec:
            return True

        if elapsed >= max_wait_sec:
            return last_size is not None and (time.monotonic() - changed_at) >= stability_sec
        sleep_fn(interval)
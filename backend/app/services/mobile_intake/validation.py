"""Validation of files arriving from a phone (M25).

The intake directory is UNTRUSTED input. Every file must pass:
  * filename sanitisation  (no traversal, no execution-ish names, plain name)
  * extension allow-list   (jpg/jpeg/png/webp only)
  * size limit             (configurable, defaults to the M17 15 MB ceiling)
  * decode probe           (cv2 can actually decode it)
before its content hash is trusted.

No network access, ever. This module is deliberately dependency-free beyond
OpenCV (already used by the codebase).
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

from ..batch_intake.package_ocr import MAX_IMAGE_BYTES

logger = logging.getLogger("storeye.mobile_intake")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_EXTENSION_LABEL = ", ".join(sorted(ALLOWED_EXTENSIONS))


def sanitise_filename(name: str) -> str:
    """Return a safe basename, or raise ``ValueError`` on anything dodgy."""
    base = os.path.basename(name.replace("\\", "/"))
    if not base or base in {".", ".."}:
        raise ValueError("empty or dot-only file name")
    if base.startswith("."):
        raise ValueError("hidden files are not processed")
    if any(ch in base for ch in ("/", "\\", "\x00")):
        raise ValueError("path separators are not allowed in file names")
    if len(base) > 240:
        raise ValueError("file name is too long")
    return base


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extension_of(name: str) -> str:
    return Path(name).suffix.lower()


def file_size_ok(size: int, max_bytes: Optional[int] = None) -> bool:
    limit = max_bytes if max_bytes is not None else MAX_IMAGE_BYTES
    return 0 < size <= limit


def validates_as_image(data: bytes) -> bool:
    if not data:
        return False
    import numpy as np
    from cv2 import imdecode

    arr = np.frombuffer(data, dtype=np.uint8)
    try:
        return imdecode(arr, 1) is not None
    except Exception:
        return False
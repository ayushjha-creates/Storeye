"""Local barcode decoding for Smart Batch Intake.

Uses pyzbar wrapping the system `zbar` (zbarimg/libzbar). Everything runs
locally — no network lookup. A barcode identifies the PRODUCT only.

macOS/Hombrew caveat: `ctypes.util.find_library("zbar")` does not always find
`/opt/homebrew/lib/libzbar.dylib`, so we bootstrap `find_library` BEFORE
importing pyzbar (pyzbar captures `find_library` at import time). The same
bootstrap covers Linux/usr/local installs.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from typing import List, Optional

from .candidate import DecodedBarcode
from .errors import BarcodeUnavailableError

logger = logging.getLogger("storeye.batch_intake.barcode_decoder")

_KNOWN_LIBZBAR_PATHS = (
    "/opt/homebrew/lib/libzbar.dylib",
    "/opt/homebrew/lib/libzbar.0.dylib",
    "/usr/local/lib/libzbar.dylib",
    "/usr/local/lib/libzbar.0.dylib",
    "/usr/lib/libzbar.dylib",
    "/usr/lib/x86_64-linux-gnu/libzbar.so.0",
    "/usr/lib/aarch64-linux-gnu/libzbar.so.0",
)


def _resolve_libzbar() -> Optional[str]:
    found = ctypes.util.find_library("zbar")
    if found:
        return found
    for path in _KNOWN_LIBZBAR_PATHS:
        if os.path.exists(path):
            return path
    return None


def _bootstrap_find_library() -> Optional[str]:
    """Patch ctypes.util.find_library so pyzbar finds a system libzbar."""
    path = _resolve_libzbar()
    if path is None:
        return None
    _find_library = ctypes.util.find_library

    def patched(name: str, *args, **kwargs):
        if name == "zbar":
            return path
        return _find_library(name, *args, **kwargs)

    ctypes.util.find_library = patched
    return path


class BarcodeDecoder:
    """Interface: decode barcodes from a BGR numpy image."""

    def decode(self, image_bgr) -> List[DecodedBarcode]:
        """Return all decoded barcodes (empty list when none found)."""
        raise NotImplementedError


class PyZbarBarcodeDecoder(BarcodeDecoder):
    """Real local decoder backed by pyzbar + system libzbar."""

    def __init__(self) -> None:
        path = _bootstrap_find_library()
        if path is None:
            raise BarcodeUnavailableError(
                "System zbar library not found. Install with "
                "'brew install zbar' (or your OS package manager)."
            )
        try:
            from pyzbar import pyzbar as _pyzbar  # noqa: F401  (import-time bind)
        except ImportError as exc:
            raise BarcodeUnavailableError(
                "pyzbar is not installed. Run: pip install pyzbar"
            ) from exc
        self._decode = _pyzbar.decode
        self._libzbar_path = path
        logger.info("PyZbarBarcodeDecoder ready using libzbar at %s", path)

    def decode(self, image_bgr) -> List[DecodedBarcode]:
        try:
            results = self._decode(image_bgr)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("zbar decode raised: %s", exc)
            return []
        decoded: List[DecodedBarcode] = []
        for item in results:
            try:
                data = item.data.decode("utf-8", errors="replace")
            except AttributeError:
                data = str(item)
            if data:
                decoded.append(
                    DecodedBarcode(
                        data=data,
                        symbology=str(getattr(item, "type", "UNKNOWN")),
                        confidence=1.0,
                    )
                )
        return decoded


class FakeBarcodeDecoder(BarcodeDecoder):
    """Deterministic test/fixture decoder.

    Returns a fixed list of barcodes on every call. Useful for unit and the
    real-AI smoke tests, and for offline demo where no camera is used.
    """

    def __init__(self, reads: Optional[List[DecodedBarcode]] = None) -> None:
        self.reads = list(reads or [])

    def decode(self, image_bgr) -> List[DecodedBarcode]:
        return list(self.reads)


def make_barcode_decoder() -> Optional[BarcodeDecoder]:
    """Build the best available local decoder (None when unavailable)."""
    try:
        return PyZbarBarcodeDecoder()
    except BarcodeUnavailableError as exc:
        logger.warning("Barcode decoding unavailable: %s", exc)
        return None
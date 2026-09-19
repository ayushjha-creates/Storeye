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
        if image_bgr is None:
            return []
        import cv2

        candidates = [image_bgr]
        try:
            candidates.append(cv2.rotate(image_bgr, cv2.ROTATE_90_CLOCKWISE))
            candidates.append(cv2.rotate(image_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE))
        except Exception:
            pass

        results = []
        for img in candidates:
            try:
                results = self._decode(img)
                if results:
                    break
            except Exception as exc:
                logger.warning("zbar decode raised: %s", exc)

        # If still nothing, try grayscale contrast enhancement
        if not results:
            try:
                gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
                results = self._decode(gray)
                if not results:
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                    results = self._decode(clahe.apply(gray))
            except Exception:
                pass

        decoded: List[DecodedBarcode] = []
        seen = set()
        for item in results:
            try:
                data = item.data.decode("utf-8", errors="replace")
            except AttributeError:
                data = str(item)
            data = data.strip()
            if data and data not in seen:
                seen.add(data)
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


class OpenCVBarcodeDecoder(BarcodeDecoder):
    """Fallback barcode decoder using OpenCV's BarcodeDetector and QRCodeDetector."""

    def __init__(self) -> None:
        import cv2

        self._barcode_det = (
            cv2.barcode.BarcodeDetector() if hasattr(cv2, "barcode") else None
        )
        self._qr_det = (
            cv2.QRCodeDetector() if hasattr(cv2, "QRCodeDetector") else None
        )

    def decode(self, image_bgr) -> List[DecodedBarcode]:
        if image_bgr is None:
            return []
        import cv2

        decoded: List[DecodedBarcode] = []
        seen = set()

        rotations = [image_bgr]
        try:
            rotations.append(cv2.rotate(image_bgr, cv2.ROTATE_90_CLOCKWISE))
            rotations.append(cv2.rotate(image_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE))
        except Exception:
            pass

        for img in rotations:
            if self._barcode_det is not None:
                try:
                    res = self._barcode_det.detectAndDecodeMulti(img)
                    if res and res[0] and res[1]:
                        for info, b_type in zip(res[1], res[2]):
                            data = str(info or "").strip()
                            if data and data not in seen:
                                seen.add(data)
                                decoded.append(
                                    DecodedBarcode(
                                        data=data,
                                        symbology=str(b_type or "BARCODE"),
                                        confidence=0.95,
                                    )
                                )
                except Exception:
                    pass

            if self._qr_det is not None and not decoded:
                try:
                    res = self._qr_det.detectAndDecodeMulti(img)
                    if res and res[0] and res[1]:
                        for info in res[1]:
                            data = str(info or "").strip()
                            if data and data not in seen:
                                seen.add(data)
                                decoded.append(
                                    DecodedBarcode(
                                        data=data,
                                        symbology="QRCODE",
                                        confidence=0.95,
                                    )
                                )
                except Exception:
                    pass

            if decoded:
                break

        return decoded


class CompositeBarcodeDecoder(BarcodeDecoder):
    """Tries pyzbar first (fastest/standard), then falls back to OpenCV's BarcodeDetector."""

    def __init__(
        self,
        primary: Optional[BarcodeDecoder] = None,
        fallback: Optional[BarcodeDecoder] = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or OpenCVBarcodeDecoder()

    def decode(self, image_bgr) -> List[DecodedBarcode]:
        if self.primary is not None:
            try:
                res = self.primary.decode(image_bgr)
                if res:
                    return res
            except Exception as exc:
                logger.warning("Primary barcode decode raised: %s", exc)

        if self.fallback is not None:
            try:
                return self.fallback.decode(image_bgr)
            except Exception as exc:
                logger.warning("Fallback barcode decode raised: %s", exc)
        return []


def make_barcode_decoder() -> Optional[BarcodeDecoder]:
    """Build the best available local decoder (pyzbar + OpenCV fallback)."""
    primary = None
    try:
        primary = PyZbarBarcodeDecoder()
    except BarcodeUnavailableError as exc:
        logger.info(
            "pyzbar barcode decoding unavailable (%s); using OpenCV fallback", exc
        )
    return CompositeBarcodeDecoder(primary=primary)
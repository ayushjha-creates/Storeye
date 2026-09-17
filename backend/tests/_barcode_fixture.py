"""Shared test fixture helpers for Smart Batch Intake tests.

Delegates to the production `app.utils.code39` module so demo assets, the
watcher E2E and tests all render byte-identical, deterministic Code-39 labels
(offline, validated against pyzbar/zbar).
"""

from __future__ import annotations

from app.utils.code39 import code39_image, package_label_bytes

__all__ = ["code39_image", "package_photo_bytes"]


def package_photo_bytes(
    *,
    barcode: str = "8901234567890",
    width: int = 1600,
    height: int = 1200,
    text_lines: tuple[str, ...] = (
        "MRP: 14.00",
        "MFG: 12/03/2026",
        "EXP: 15/12/2026",
        "BATCH: M24031",
    ),
) -> bytes:
    """Render a close-up package label + barcode and return JPEG bytes.

    Offline-only: pure OpenCV drawing + the Code-39 generator (no camera).
    """
    return package_label_bytes(
        barcode=barcode, width=width, height=height, text_lines=text_lines
    )
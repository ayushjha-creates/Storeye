"""Deterministic demo package images for the USB intake demo (M25).

The images are rendered OFFLINE (OpenCV + the Code-39 encoder) and watermarked
so nobody mistakes them for real photos. Each barcode belongs to a seeded demo
catalogue product, so the real M17 pipeline resolves it to a real catalog
product — nothing is faked: the same code path decodes the barcode, runs OCR
and evaluates expiry that a camera photo would go through.

OCR never invents text: every demo pack carries the classic MRP/MFG/EXP/BATCH
lines a printed retail pack shows.
"""

from __future__ import annotations

from typing import Optional

from ...utils.code39 import package_label_bytes

DEMO_WATERMARK = "DEMO - NOT A REAL PHOTO"

# Seeded demo catalogue products (demo/seed_demo.py PRODUCTS + barcodes).
# slug -> name, barcode, rendered label lines.
DEMO_PACKAGES: dict[str, dict] = {
    "aashirvaad": {
        "product_name": "Aashirvaad Atta 5kg",
        "barcode": "8901063001015",  # AAS-ATTA
        "batch": "M25-DEMO-01",
        "text_lines": ("MRP: 240.00", "MFG: 08/2026", "EXP: 08/2027", "BATCH: M25-DEMO-01"),
    },
    "amul": {
        "product_name": "Amul Milk 1L",
        "barcode": "8901262030003",  # AMUL-MILK
        "batch": "M25-DEMO-02",
        "text_lines": ("MRP: 62.00", "MFG: 15/09/2026", "EXP: 16/09/2026", "BATCH: M25-DEMO-02"),
    },
}

DEFAULT_DEMO_PACKAGE = "aashirvaad"


def demo_package_slugs() -> list[str]:
    """Deterministic catalogue order for the demo-queue UI/tests."""
    return list(DEMO_PACKAGES)


def _spec(slug: Optional[str]) -> dict:
    if not slug or slug not in DEMO_PACKAGES:
        slug = DEFAULT_DEMO_PACKAGE
    return DEMO_PACKAGES[slug]


def build_demo_intake_bytes(slug: Optional[str] = None) -> bytes:
    """Return the byte-identical demo package photo for ``slug`` (or the
    default Aashirvaad pack). Same bytes every call for a given slug."""
    spec = _spec(slug)
    return package_label_bytes(
        barcode=spec["barcode"],
        text_lines=spec["text_lines"],
        demo_watermark=DEMO_WATERMARK,
        format_=".jpg",
    )


def build_demo_intake_meta(slug: Optional[str] = None) -> dict:
    """Product metadata for a demo package slug (for API responses/tests)."""
    resolved = slug or DEFAULT_DEMO_PACKAGE
    if resolved not in DEMO_PACKAGES:
        resolved = DEFAULT_DEMO_PACKAGE
    spec = DEMO_PACKAGES[resolved]
    return {
        "slug": resolved,
        "product_name": spec["product_name"],
        "barcode": spec["barcode"],
        "batch": spec["batch"],
    }
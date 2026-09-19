"""Candidate model for a Smart Batch Intake scan.

A `PackageScan` is the RESULT of one close-up package scan. It is strictly a
*read-only candidate*: nothing here is ever written to the database. The
shopkeeper reviews/edits it, types the quantity and the API confirmation
endpoint turns it into a real batch + inventory movement via the existing
domain services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from datetime import date

from ..product.expiry_parser import ParsedProductMetadata

# Human-facing message used whenever the scan cannot confidently read enough.
UNABLE_TO_READ_MESSAGE = (
    "Unable to confidently read package information. "
    "Retake the photo (flat, well-lit, filling the frame) or enter the values manually."
)


@dataclass
class DecodedBarcode:
    """A single decoded barcode value."""

    data: str
    symbology: str
    confidence: float = 1.0


@dataclass
class PackageScanCandidate:
    """Editable prefill produced by a scan (never written back to DB)."""

    barcode_read: bool = False
    barcode: Optional[str] = None
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    product_sku: Optional[str] = None
    product_found: bool = False
    batch_number: Optional[str] = None
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    expiry_date_precision: str = "day"
    mrp: Optional[Decimal] = None
    confidence: Optional[float] = None
    labels_found: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PackageScan:
    """Outcome of a scan: acceptability verdict + editable candidate."""

    acceptable: bool
    reason: str
    candidate: PackageScanCandidate
    store_id: Optional[str] = None

    @classmethod
    def from_parsed(
        cls,
        parsed: ParsedProductMetadata,
        *,
        barcode_read: bool,
        barcode: Optional[str],
        product_id: Optional[str],
        product_name: Optional[str],
        product_sku: Optional[str],
        product_found: bool,
        store_id: Optional[str] = None,
    ) -> "PackageScan":
        """Assemble a scan outcome from parser/barcode results.

        `acceptable` is true when we can offer a useful prefill: either a
        barcode was decoded or at least one structured field was parsed.
        Only when nothing at all could be read do we refuse to guess.
        """
        labels_found = [
            label
            for label, present in (
                ("expiry", parsed.expiry_date is not None),
                ("manufacturing", parsed.manufacturing_date is not None),
                ("batch", parsed.batch_number is not None),
                ("mrp", parsed.mrp is not None),
            )
            if present
        ]
        warnings = list(parsed.warnings)

        if not barcode_read and not labels_found and not product_found:
            return cls(
                acceptable=False,
                reason=UNABLE_TO_READ_MESSAGE,
                candidate=PackageScanCandidate(
                    barcode_read=barcode_read,
                    barcode=barcode,
                    product_id=product_id,
                    product_name=product_name,
                    product_sku=product_sku,
                    product_found=product_found,
                    confidence=parsed.confidence,
                    warnings=warnings,
                ),
                store_id=store_id,
            )

        notes: list[str] = []
        if product_found:
            if barcode_read:
                notes.append(f"Barcode matched product '{product_name}'.")
            else:
                notes.append(f"Identified product '{product_name}' from packaging.")
        elif barcode_read:
            notes.append("Barcode is not linked to any product. Select a product to continue.")
        else:
            notes.append("Select a product to continue.")

        if not labels_found:
            notes.append("No expiry/batch text found. Enter the values below or retake the photo.")

        return cls(
            acceptable=True,
            reason=" ".join(notes),
            candidate=PackageScanCandidate(
                barcode_read=barcode_read,
                barcode=barcode,
                product_id=product_id,
                product_name=product_name,
                product_sku=product_sku,
                product_found=product_found,
                batch_number=parsed.batch_number,
                manufacturing_date=parsed.manufacturing_date,
                expiry_date=parsed.expiry_date,
                expiry_date_precision=parsed.expiry_date_precision,
                mrp=parsed.mrp,
                confidence=parsed.confidence,
                labels_found=labels_found,
                warnings=warnings,
            ),
            store_id=store_id,
        )
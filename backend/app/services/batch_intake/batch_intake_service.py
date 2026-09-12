"""BatchIntakeService — Smart Batch Receiving orchestration.

Scan (READ-ONLY)
    Close-up photo -> quality gate -> barcode decode -> local Product lookup
    -> PaddleOCR text -> ExpiryParser -> editable `PackageScan` candidate.
    Scanning NEVER mutates inventory/batches/products.

Confirm (ATOMIC, HUMAN-CONFIRMED)
    The shopkeeper reviews/edits the candidate and types a quantity. The
    confirmation reuses the existing BatchService + InventoryService: a batch
    row is added and flushed, then `InventoryService.receive_stock(batch_id=...)`
    commits the inventory aggregate, the batch quantity and the movement in a
    SINGLE transaction (all-or-nothing). Existing-domain validation is reused,
    not re-implemented.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BATCH_PRECISION_DAY, Batch, Product, Store
from app.services.inventory.batch_service import BatchService
from app.services.inventory.errors import (
    EntityNotFoundError,
    ValidationError,
)
from app.services.inventory.inventory_service import InventoryService, PURCHASE
from app.services.product.expiry_parser import ExpiryParser

from .barcode_decoder import BarcodeDecoder, make_barcode_decoder
from .candidate import DecodedBarcode, PackageScan
from .errors import ImageDecodeError, ImageQualityError
from .package_ocr import PackageOCRProcessor, check_quality, decode_image_bytes

logger = logging.getLogger("storeye.batch_intake.service")


class BatchIntakeService:
    def __init__(
        self,
        session: Session,
        *,
        barcode_decoder: Optional[BarcodeDecoder] = None,
        ocr_processor: Optional[PackageOCRProcessor] = None,
        parser: Optional[ExpiryParser] = None,
    ) -> None:
        self.session = session
        # None -> best available local decoder (may silently degrade to none).
        self.barcode_decoder = barcode_decoder if barcode_decoder is not None else make_barcode_decoder()
        self.ocr_processor = ocr_processor or PackageOCRProcessor()
        self.parser = parser or ExpiryParser()
        self.inventory = InventoryService(session)  # reused (holds BatchService)

    # ------------------------------------------------------------------
    # Scan (read-only)
    # ------------------------------------------------------------------
    def scan_package(self, image_bytes: bytes, *, store_id=None) -> PackageScan:
        """Scan a close-up package photo into an editable candidate.

        No database mutation happens here (not even a read of anything
        business-critical beyond the LOCAL product catalog lookup).
        """
        image = decode_image_bytes(image_bytes)  # raises ImageDecodeError

        problems = check_quality(image, self.ocr_processor.quality)
        if problems:
            raise ImageQualityError(" ".join(problems))

        barcode = self._decode_barcode(image)
        product = (
            self._resolve_product(barcode.data, store_id=store_id)
            if barcode is not None
            else None
        )

        ocr_result, notes = self.ocr_processor.run(image)
        parsed = self.parser.parse(ocr_result)
        for note in notes:
            parsed.warnings.append(note)

        return PackageScan.from_parsed(
            parsed,
            barcode_read=barcode is not None,
            barcode=barcode.data if barcode is not None else None,
            product_id=str(product.id) if product is not None else None,
            product_name=product.name if product is not None else None,
            product_sku=product.sku if product is not None else None,
            product_found=product is not None,
            store_id=str(store_id) if store_id is not None else None,
        )

    # ------------------------------------------------------------------
    # Confirm (atomic, human-confirmed)
    # ------------------------------------------------------------------
    def confirm_receipt(
        self,
        *,
        store_id,
        product_id,
        quantity: int,
        batch_number: Optional[str] = None,
        manufacturing_date=None,
        expiry_date=None,
        expiry_date_precision: str = BATCH_PRECISION_DAY,
        mrp=None,
        reference: Optional[str] = None,
    ) -> Tuple[Batch, object]:
        """Commit a shopkeeper-confirmed receipt atomically.

        Returns (Batch, InventoryMovement). Validation and the single
        transaction live in the reused domain services: the new batch row is
        flushed (so it has an id), then `InventoryService.receive_stock`
        updates the aggregate inventory + batch quantity + movement in one
        commit. On any failure the whole transaction (including the new batch
        row) rolls back.
        """
        store = self.session.get(Store, store_id)
        if store is None:
            raise EntityNotFoundError(f"Store {store_id} does not exist.")
        product = self.session.get(Product, product_id)
        if product is None:
            raise EntityNotFoundError(f"Product {product_id} does not exist.")

        quantity = int(quantity)
        if quantity <= 0:
            raise ValidationError("quantity must be at least 1.")

        # Reuse the existing domain batch validation (dates/MRP/precision/quantity).
        BatchService._validate_batch(
            manufacturing_date=manufacturing_date,
            expiry_date=expiry_date,
            expiry_date_precision=expiry_date_precision,
            mrp=mrp,
            quantity=quantity,
        )

        normalized_batch_number = BatchService._normalize_batch_number(batch_number)
        try:
            batch = None
            if normalized_batch_number is not None:
                batch = self.inventory.batches.get_batch(
                    store_id=store_id,
                    product_id=product_id,
                    batch_number=normalized_batch_number,
                )

            if batch is None:
                batch = Batch(
                    store_id=store_id,
                    product_id=product_id,
                    batch_number=normalized_batch_number,
                    manufacturing_date=manufacturing_date,
                    expiry_date=expiry_date,
                    expiry_date_precision=expiry_date_precision,
                    mrp=mrp,
                    quantity=0,
                )
                self.session.add(batch)
                self.session.flush()

            movement = self.inventory.receive_stock(
                store_id=store_id,
                product_id=product_id,
                quantity_change=quantity,
                batch_id=batch.id,
                reference=reference,
                movement_type=PURCHASE,
            )
            # receive_stock committed; refresh to be safe against expired state.
            self.session.refresh(batch)
        except Exception:
            self.session.rollback()
            raise
        return batch, movement

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _decode_barcode(self, image) -> Optional[DecodedBarcode]:
        if self.barcode_decoder is None:
            return None
        try:
            reads = self.barcode_decoder.decode(image) or []
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Barcode decode failed: %s", exc)
            return None
        if not reads:
            return None
        return reads[0]

    def _resolve_product(self, barcode: str, *, store_id):
        query = select(Product).where(Product.barcode == barcode.strip())
        if store_id is not None:
            query = query.where(Product.store_id == store_id)
        return self.session.scalars(query.order_by(Product.name).limit(1)).first()
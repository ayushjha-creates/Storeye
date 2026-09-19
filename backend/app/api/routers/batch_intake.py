"""Smart Batch Intake API routes.

    POST /api/batch-intake/scan     read-only close-up scan -> editable candidate
    POST /api/batch-intake/confirm  human-confirmed receipt -> atomic batch + movement

Scanning performs NO database mutation. Confirmation performs exactly one
atomic transaction via the existing BatchService/InventoryService.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ..authz import effective_store_id, require_same_store
from ..deps import get_db, require_role
from ...models import User
from ...schemas import (
    BatchReceiptRead,
    BatchScanRead,
)
from ...schemas.batch_intake import BatchConfirmIn, BatchScanCandidateRead
from ...services.batch_intake import BatchIntakeService
from ...services.batch_intake.errors import ImageDecodeError

router = APIRouter(prefix="/batch-intake", tags=["batch-intake"])


def _check_upload_is_image(content_type: Optional[str]) -> None:
    if content_type and not content_type.lower().startswith("image/"):
        raise ImageDecodeError(
            f"Upload must be an image, got '{content_type}'. "
            "Clean barcode photos (PNG/JPEG/WebP) are supported."
        )


def _to_candidate(candidate) -> BatchScanCandidateRead:
    return BatchScanCandidateRead(
        barcode_read=candidate.barcode_read,
        barcode=candidate.barcode,
        product_id=candidate.product_id,
        product_name=candidate.product_name,
        product_sku=candidate.product_sku,
        product_found=candidate.product_found,
        batch_number=candidate.batch_number,
        manufacturing_date=candidate.manufacturing_date,
        expiry_date=candidate.expiry_date,
        expiry_date_precision=candidate.expiry_date_precision,
        mrp=candidate.mrp,
        confidence=candidate.confidence,
        labels_found=candidate.labels_found,
        warnings=candidate.warnings,
    )


@router.post("/scan", response_model=BatchScanRead)
def scan_package(
    file: UploadFile = File(...),
    store_id: Optional[UUID] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Scan a close-up package photo into an editable candidate.

    Read-only: no inventory, batch or product is created or changed.
    An image that cannot be decoded or read is rejected with a clear message
    (never guessed).
    """
    _check_upload_is_image(file.content_type)
    sid = effective_store_id(current_user, store_id)
    service = BatchIntakeService(db)
    scan = service.scan_package(file.file.read(), store_id=sid)
    return BatchScanRead(
        store_id=scan.store_id,
        acceptable=scan.acceptable,
        reason=scan.reason,
        candidate=_to_candidate(scan.candidate),
    )


@router.post("/confirm", response_model=BatchReceiptRead, status_code=201)
def confirm_batch(
    payload: BatchConfirmIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Commit a shopkeeper-confirmed receipt (batch + inventory + movement).

    Atomic: the batch row and the inventory/movement mutation are committed in
    a single transaction through the existing domain services.
    """
    require_same_store(current_user, payload.store_id)
    service = BatchIntakeService(db)
    batch, movement = service.confirm_receipt(
        store_id=payload.store_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        batch_number=payload.batch_number,
        manufacturing_date=payload.manufacturing_date,
        expiry_date=payload.expiry_date,
        expiry_date_precision=payload.expiry_date_precision,
        mrp=payload.mrp,
        reference=payload.reference,
        barcode=payload.barcode,
    )
    return BatchReceiptRead(
        movement=movement,
        batch=batch,
    )
"""BatchService — explicit domain operations for product batches.

This service is the single, explicit way to create/find Batch records. It
receives already-parsed/validated metadata (e.g. from ExpiryParser via an
application layer) — it NEVER calls PaddleOCR or the parser itself, keeping
AI and business logic decoupled.

Every operation is transactional: it runs within the injected Session and
either commits all changes or rolls back, so partial writes (batch created
but something else missing) are impossible.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Batch, BATCH_PRECISION_DAY, Store, Product
from .errors import (
    BatchMismatchError,
    DuplicateBatchError,
    EntityNotFoundError,
    ValidationError,
)

# Allowed precision values (mirror the parser).
_VALID_PRECISIONS = {"day", "month"}


class BatchService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------
    def create_batch(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        batch_number: Optional[str] = None,
        manufacturing_date: Optional[date] = None,
        expiry_date: Optional[date] = None,
        expiry_date_precision: str = BATCH_PRECISION_DAY,
        mrp: Optional[Decimal] = None,
        quantity: int = 0,
    ) -> Batch:
        """Create a new Batch with validation, atomically.

        Raises:
            EntityNotFoundError: store/product does not exist.
            DuplicateBatchError: another batch with the same
                (store, product, batch_number) exists (batch_number != None).
            ValidationError: dates/MRP/quantity/precision invalid.
        """
        store = self._require(Store, store_id, "Store")
        product = self._require(Product, product_id, "Product")
        del store  # existence checked; used only for validation

        self._validate_batch(
            manufacturing_date=manufacturing_date,
            expiry_date=expiry_date,
            expiry_date_precision=expiry_date_precision,
            mrp=mrp,
            quantity=quantity,
        )

        normalized_batch_number = self._normalize_batch_number(batch_number)
        if normalized_batch_number is not None:
            self._ensure_unique_batch(product_id, store_id, normalized_batch_number)

        batch = Batch(
            store_id=store_id,
            product_id=product_id,
            batch_number=normalized_batch_number,
            manufacturing_date=manufacturing_date,
            expiry_date=expiry_date,
            expiry_date_precision=expiry_date_precision,
            mrp=mrp,
            quantity=quantity,
        )
        self.session.add(batch)
        try:
            self.session.flush()
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        # Re-query so the instance is bound to the (fresh) session state.
        self.session.refresh(batch)
        return batch

    def get_batch(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        batch_number: str,
    ) -> Optional[Batch]:
        return (
            self.session.query(Batch)
            .filter(
                Batch.store_id == store_id,
                Batch.product_id == product_id,
                Batch.batch_number == batch_number,
            )
            .first()
        )

    def get_batch_by_id(self, batch_id: UUID) -> Optional[Batch]:
        return self.session.get(Batch, batch_id)

    def get_batches_for_product(self, store_id: UUID, product_id: UUID) -> list[Batch]:
        return (
            self.session.query(Batch)
            .filter(
                Batch.store_id == store_id,
                Batch.product_id == product_id,
            )
            .order_by(Batch.batch_number)
            .all()
        )

    def ensure_batch(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        batch_number: str,
        manufacturing_date: Optional[date] = None,
        expiry_date: Optional[date] = None,
        expiry_date_precision: str = BATCH_PRECISION_DAY,
        mrp: Optional[Decimal] = None,
    ) -> Batch:
        """Return the existing batch or create it (find-or-create).

        Used by inbound stock operations where a batch may legitimately
        already exist. Validation is still applied on creation.
        """
        existing = self.get_batch(
            store_id=store_id, product_id=product_id, batch_number=batch_number
        )
        if existing is not None:
            return existing
        return self.create_batch(
            store_id=store_id,
            product_id=product_id,
            batch_number=batch_number,
            manufacturing_date=manufacturing_date,
            expiry_date=expiry_date,
            expiry_date_precision=expiry_date_precision,
            mrp=mrp,
            quantity=0,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _require(self, model, pk: UUID, label: str):
        obj = self.session.get(model, pk)
        if obj is None:
            raise EntityNotFoundError(f"{label} {pk} does not exist.")
        return obj

    @staticmethod
    def _normalize_batch_number(batch_number: Optional[str]) -> Optional[str]:
        if batch_number is None:
            return None
        stripped = batch_number.strip()
        if not stripped:
            return None
        return stripped

    def _ensure_unique_batch(self, product_id, store_id, batch_number) -> None:
        exists = (
            self.session.query(Batch)
            .filter(
                Batch.store_id == store_id,
                Batch.product_id == product_id,
                Batch.batch_number == batch_number,
            )
            .first()
        )
        if exists is not None:
            raise DuplicateBatchError(
                f"Batch '{batch_number}' already exists for this product and store."
            )

    @staticmethod
    def _validate_batch(
        *,
        manufacturing_date: Optional[date],
        expiry_date: Optional[date],
        expiry_date_precision: str,
        mrp: Optional[Decimal],
        quantity: int,
    ) -> None:
        if expiry_date_precision not in _VALID_PRECISIONS:
            raise ValidationError(
                f"Invalid expiry_date_precision '{expiry_date_precision}'; "
                f"expected one of {sorted(_VALID_PRECISIONS)}."
            )
        for name, value in (
            ("manufacturing_date", manufacturing_date),
            ("expiry_date", expiry_date),
        ):
            if value is not None and not isinstance(value, date):
                raise ValidationError(
                    f"{name} must be a datetime.date, got {type(value).__name__}."
                )
        if manufacturing_date is not None and expiry_date is not None:
            if expiry_date < manufacturing_date:
                raise ValidationError(
                    "expiry_date cannot be before manufacturing_date "
                    f"({expiry_date.isoformat()} < {manufacturing_date.isoformat()})."
                )
        if mrp is not None and mrp < 0:
            raise ValidationError(f"mrp cannot be negative ({mrp}).")
        if quantity < 0:
            raise ValidationError(f"quantity cannot be negative ({quantity}).")


def validate_batch_belongs(batch: Batch, store_id, product_id) -> None:
    """Confirm a batch belongs to the given store and product."""
    if batch.store_id != store_id or batch.product_id != product_id:
        raise BatchMismatchError(
            "Batch does not belong to the given store/product."
        )
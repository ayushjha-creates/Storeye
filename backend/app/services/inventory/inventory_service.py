"""InventoryService — explicit domain operations for stock.

This is the ONLY place that mutates Inventory / InventoryMovement. It
performs all mutations within a single Session transaction and commits
together, so the aggregate product inventory, the batch quantity and the
movement record are all-or-nothing.

No FEFO selection, no expiry-based recommendation, no stock blocking: an
explicit `batch_id`/`batch_number` must be supplied by the caller to scope a
movement to a batch.
"""

from __future__ import annotations

from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Batch, Inventory, InventoryMovement, Product, Store
from .batch_service import BatchService, validate_batch_belongs
from .errors import EntityNotFoundError, ValidationError

# Movement types used by inbound/outbound stock operations.
PURCHASE = "PURCHASE"
SALE = "SALE"
RETURN = "RETURN"
ADJUSTMENT = "ADJUSTMENT"
DAMAGE = "DAMAGE"

_VALID_MOVEMENT_TYPES = {
    PURCHASE,
    SALE,
    RETURN,
    ADJUSTMENT,
    DAMAGE,
    "EXPIRY",
    "TRANSFER",
}


class InventoryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.batches = BatchService(session)

    # ------------------------------------------------------------------
    # Stock operations
    # ------------------------------------------------------------------
    def receive_stock(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        quantity_change: int,
        batch_id: Optional[UUID] = None,
        batch_number: Optional[str] = None,
        reference: Optional[str] = None,
        movement_type: str = PURCHASE,
    ) -> InventoryMovement:
        """Add stock. May be scoped to a batch.

        If `batch_id` or `batch_number` is given, the batch must exist and
        belong to store_id/product_id. Its quantity is updated together with
        the aggregate Inventory and the movement — atomically.
        """
        self._validate_quantity(quantity_change, allow_negative=True)
        store = self._require(Store, store_id, "Store")
        product = self._require(Product, product_id, "Product")
        del store, product

        batch = self._resolve_batch(
            store_id=store_id,
            product_id=product_id,
            batch_id=batch_id,
            batch_number=batch_number,
        )
        return self._apply_movement(
            store_id=store_id,
            product_id=product_id,
            quantity_change=quantity_change,
            movement_type=movement_type,
            batch=batch,
            reference=reference,
        )

    def adjust_stock(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        quantity_change: int,
        batch_id: Optional[UUID] = None,
        batch_number: Optional[str] = None,
        reference: Optional[str] = None,
        movement_type: str = ADJUSTMENT,
        require_sufficient_stock: bool = False,
    ) -> InventoryMovement:
        """Adjust stock (positive or negative change).

        Optionally enforce that the resulting aggregate Inventory quantity
        does not go negative when `require_sufficient_stock` is True.
        """
        self._validate_quantity(quantity_change)
        store = self._require(Store, store_id, "Store")
        product = self._require(Product, product_id, "Product")
        del store, product

        batch = self._resolve_batch(
            store_id=store_id,
            product_id=product_id,
            batch_id=batch_id,
            batch_number=batch_number,
        )

        if require_sufficient_stock:
            current = self._get_or_create_inventory(store_id, product_id).quantity
            if current + quantity_change < 0:
                raise ValidationError(
                    f"Not enough stock: current={current}, change={quantity_change}."
                )
        return self._apply_movement(
            store_id=store_id,
            product_id=product_id,
            quantity_change=quantity_change,
            movement_type=movement_type,
            batch=batch,
            reference=reference,
        )

    def record_movement(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        quantity_change: int,
        movement_type: str,
        batch_id: Optional[UUID] = None,
        batch_number: Optional[str] = None,
        reference: Optional[str] = None,
    ) -> InventoryMovement:
        """Record a movement, updating Inventory (and batch) atomically."""
        self._require(Store, store_id, "Store")
        self._require(Product, product_id, "Product")
        self._validate_movement_type(movement_type)
        batch = self._resolve_batch(
            store_id=store_id,
            product_id=product_id,
            batch_id=batch_id,
            batch_number=batch_number,
        )
        return self._apply_movement(
            store_id=store_id,
            product_id=product_id,
            quantity_change=quantity_change,
            movement_type=movement_type,
            batch=batch,
            reference=reference,
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_product_inventory(self, store_id: UUID, product_id: UUID) -> Inventory:
        inv = (
            self.session.query(Inventory)
            .filter(
                Inventory.store_id == store_id,
                Inventory.product_id == product_id,
            )
            .first()
        )
        if inv is None:
            # Empty aggregate — report as a zero-quantity aggregate row.
            return Inventory(
                store_id=store_id,
                product_id=product_id,
                quantity=0,
                reorder_level=0,
                reorder_quantity=0,
            )
        return inv

    def get_batch_inventory(
        self, store_id: UUID, product_id: UUID
    ) -> list[Batch]:
        return (
            self.session.query(Batch)
            .filter(
                Batch.store_id == store_id,
                Batch.product_id == product_id,
            )
            .order_by(Batch.batch_number)
            .all()
        )

    def get_product_batch_summary(
        self, store_id: UUID, product_id: UUID
    ) -> Tuple[int, list[Batch]]:
        """Return (aggregate_quantity, batches) for a product in a store."""
        aggregate = self.get_product_inventory(store_id, product_id).quantity
        return aggregate, self.get_batch_inventory(store_id, product_id)

    # ------------------------------------------------------------------
    # Internals — mutation is applied atomically here
    # ------------------------------------------------------------------
    def _apply_movement(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        quantity_change: int,
        movement_type: str,
        batch: Optional[Batch],
        reference: Optional[str],
    ) -> InventoryMovement:
        try:
            inv = self._get_or_create_inventory(store_id, product_id)
            inv.quantity += quantity_change

            if batch is not None:
                batch.quantity += quantity_change

            movement = InventoryMovement(
                store_id=store_id,
                product_id=product_id,
                batch_id=batch.id if batch else None,
                quantity_change=quantity_change,
                movement_type=movement_type,
                reference=reference,
            )
            self.session.add(movement)
            self.session.commit()
            self.session.refresh(movement)
            return movement
        except Exception:
            self.session.rollback()
            raise

    def _get_or_create_inventory(self, store_id: UUID, product_id: UUID) -> Inventory:
        inv = (
            self.session.query(Inventory)
            .filter(
                Inventory.store_id == store_id,
                Inventory.product_id == product_id,
            )
            .first()
        )
        if inv is None:
            inv = Inventory(
                store_id=store_id,
                product_id=product_id,
                quantity=0,
                reorder_level=0,
                reorder_quantity=0,
            )
            self.session.add(inv)
        return inv

    def _resolve_batch(
        self,
        *,
        store_id: UUID,
        product_id: UUID,
        batch_id: Optional[UUID],
        batch_number: Optional[str],
    ) -> Optional[Batch]:
        if batch_id is not None:
            batch = self.session.get(Batch, batch_id)
            if batch is None:
                raise EntityNotFoundError(f"Batch {batch_id} does not exist.")
            validate_batch_belongs(batch, store_id, product_id)
            return batch
        if batch_number is not None:
            batch = self.batches.get_batch(
                store_id=store_id,
                product_id=product_id,
                batch_number=batch_number,
            )
            if batch is None:
                raise EntityNotFoundError(
                    f"Batch '{batch_number}' does not exist for this product/store."
                )
            return batch
        return None

    def _require(self, model, pk: UUID, label: str):
        obj = self.session.get(model, pk)
        if obj is None:
            raise EntityNotFoundError(f"{label} {pk} does not exist.")
        return obj

    @staticmethod
    def _validate_quantity(quantity_change: int, allow_negative: bool = True) -> None:
        if quantity_change == 0:
            raise ValidationError("quantity_change cannot be zero.")
        if not allow_negative and quantity_change < 0:
            raise ValidationError("quantity_change must be positive for this operation.")

    @staticmethod
    def _validate_movement_type(movement_type: str) -> None:
        if movement_type.upper() not in _VALID_MOVEMENT_TYPES:
            raise ValidationError(
                f"Invalid movement_type '{movement_type}'; "
                f"expected one of {sorted(_VALID_MOVEMENT_TYPES)}."
            )
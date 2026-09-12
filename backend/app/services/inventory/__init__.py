"""Storeye inventory & batch domain services.

Explicit, transactional operations for inventory (aggregate) and batch
(per-batch) stock. AI/OCR is kept OUT of this layer — callers pass already
parsed/validated metadata.
"""

from .batch_service import BatchService, validate_batch_belongs
from .inventory_service import (
    ADJUSTMENT,
    DAMAGE,
    PURCHASE,
    RETURN,
    SALE,
    InventoryService,
)
from .errors import (
    BatchMismatchError,
    DuplicateBatchError,
    EntityNotFoundError,
    StoreyeInventoryError,
    ValidationError,
)

__all__ = [
    "BatchService",
    "validate_batch_belongs",
    "InventoryService",
    "PURCHASE",
    "SALE",
    "RETURN",
    "ADJUSTMENT",
    "DAMAGE",
    "BatchMismatchError",
    "DuplicateBatchError",
    "EntityNotFoundError",
    "StoreyeInventoryError",
    "ValidationError",
]
"""Domain exceptions for the Storeye inventory/batch layer."""

from __future__ import annotations


class StoreyeInventoryError(Exception):
    """Base class for inventory domain errors."""


class ValidationError(StoreyeInventoryError):
    """Input failed validation."""


class EntityNotFoundError(StoreyeInventoryError):
    """A referenced entity (store/product/batch) does not exist."""


class DuplicateBatchError(StoreyeInventoryError):
    """A batch with the same (store, product, number) already exists."""


class BatchMismatchError(StoreyeInventoryError):
    """A batch does not belong to the given store/product."""
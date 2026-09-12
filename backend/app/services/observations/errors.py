"""Exceptions for the Storeye observation layer."""

from __future__ import annotations


class StoreyeObservationError(Exception):
    """Base class for observation-layer errors."""


class ValidationError(StoreyeObservationError):
    """Observation input failed validation."""


class EntityNotFoundError(StoreyeObservationError):
    """A referenced entity (store/camera/product) does not exist."""
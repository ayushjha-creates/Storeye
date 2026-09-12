"""Exceptions for the Storeye alert layer."""

from __future__ import annotations


class StoreyeAlertError(Exception):
    """Base class for alert-layer errors."""


class ValidationError(StoreyeAlertError):
    """Alert input failed validation (unknown type/severity, empty title...)."""


class InvalidStatusTransitionError(ValidationError):
    """A status change violates the alert lifecycle (e.g. RESOLVED -> OPEN)."""


class EntityNotFoundError(StoreyeAlertError):
    """A referenced alert or entity does not exist."""
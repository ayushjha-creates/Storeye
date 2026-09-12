"""Storeye AI <-> Inventory reconciliation layer.

Reconciliation COMPARES persisted AI PRODUCT observations against recorded
inventory and produces ReconciliationResult rows. It NEVER mutates inventory,
creates movements, creates batches, or changes stock in any way.

    ReconciliationService   -> run reconciliation, persist results
"""

from .reconciliation_service import ReconciliationService, DEFAULT_MIN_CONFIDENCE

__all__ = ["ReconciliationService", "DEFAULT_MIN_CONFIDENCE"]
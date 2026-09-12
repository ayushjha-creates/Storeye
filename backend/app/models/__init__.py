"""Storeye business/data models (PostgreSQL-backed).

Importing this package registers all models on the SQLAlchemy Base
metadata so Alembic can autogenerate migrations, and `create_all` can
build the full schema.
"""

from .store import Store
from .user import User
from .camera import Camera
from .zone import Zone
from .shelf import Shelf
from .product import Product
from .inventory import Inventory
from .inventory_movement import InventoryMovement
from .batch import Batch, BATCH_PRECISION_DAY, BATCH_PRECISION_MONTH
from .planogram import Planogram, PlanogramItem
from .customer import Customer
from .sale import Sale, SaleItem
from .bill import Bill, BillItem
from .notification import Notification
from .alert import (
    Alert,
    ALERT_SHORTAGE,
    ALERT_SURPLUS,
    ALERT_MISPLACEMENT,
    ALERT_EXPIRY,
    ALERT_LOW_SHELF_OCCUPANCY,
    ALERT_CAMERA_OFFLINE,
    ALERT_REVIEW_REQUIRED,
    VALID_ALERT_TYPES,
    SEV_INFO,
    SEV_LOW,
    SEV_MEDIUM,
    SEV_HIGH,
    SEV_CRITICAL,
    VALID_SEVERITIES,
    STATUS_OPEN,
    STATUS_ACKNOWLEDGED,
    STATUS_RESOLVED,
    STATUS_DISMISSED,
    VALID_STATUSES,
    ALLOWED_TRANSITIONS,
)
from .observation import (
    Observation,
    OBS_PERSON,
    OBS_PRODUCT,
    OBS_TEXT,
    OBS_EXPIRY_METADATA,
    VALID_OBSERVATION_TYPES,
)
from .reconciliation_result import (
    ReconciliationResult,
    REC_MATCH,
    REC_SURPLUS,
    REC_SHORTAGE,
    REC_REVIEW,
    VALID_RECONCILIATION_STATUSES,
)

__all__ = [
    "Store",
    "User",
    "Camera",
    "Zone",
    "Shelf",
    "Product",
    "Inventory",
    "InventoryMovement",
    "Batch",
    "BATCH_PRECISION_DAY",
    "BATCH_PRECISION_MONTH",
    "Planogram",
    "PlanogramItem",
    "Customer",
    "Sale",
    "SaleItem",
    "Bill",
    "BillItem",
    "Notification",
    "Alert",
    "ALERT_SHORTAGE",
    "ALERT_SURPLUS",
    "ALERT_MISPLACEMENT",
    "ALERT_EXPIRY",
    "ALERT_LOW_SHELF_OCCUPANCY",
    "ALERT_CAMERA_OFFLINE",
    "ALERT_REVIEW_REQUIRED",
    "VALID_ALERT_TYPES",
    "SEV_INFO",
    "SEV_LOW",
    "SEV_MEDIUM",
    "SEV_HIGH",
    "SEV_CRITICAL",
    "VALID_SEVERITIES",
    "STATUS_OPEN",
    "STATUS_ACKNOWLEDGED",
    "STATUS_RESOLVED",
    "STATUS_DISMISSED",
    "VALID_STATUSES",
    "ALLOWED_TRANSITIONS",
    "Observation",
    "OBS_PERSON",
    "OBS_PRODUCT",
    "OBS_TEXT",
    "OBS_EXPIRY_METADATA",
    "VALID_OBSERVATION_TYPES",
    "ReconciliationResult",
    "REC_MATCH",
    "REC_SURPLUS",
    "REC_SHORTAGE",
    "REC_REVIEW",
    "VALID_RECONCILIATION_STATUSES",
]
"""API routers for the Storeye FastAPI application."""

from . import stores, users, cameras, zones, shelves, products
from . import (
    inventory,
    customers,
    sales,
    bills,
    notifications,
    observations,
    reconciliation,
    intelligence,
    alerts,
    batch_intake,
    demo,
    journeys,
    insights,
    mobile_intake,
)

__all__ = [
    "stores",
    "users",
    "cameras",
    "zones",
    "shelves",
    "products",
    "inventory",
    "customers",
    "sales",
    "bills",
    "notifications",
    "observations",
    "reconciliation",
    "intelligence",
    "alerts",
    "batch_intake",
    "demo",
    "journeys",
    "insights",
    "mobile_intake",
]
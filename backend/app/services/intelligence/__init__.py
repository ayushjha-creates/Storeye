"""Storeye retail intelligence layer.

Derives insights from persisted PostgreSQL data (Inventory, Batch,
InventoryMovement, ReconciliationResult) and from real Edge AI observations
(Product/Shelf Intelligence, M15). Everything here is DERIVED INTELLIGENCE —
calculated dynamically, never persisted, and NEVER writing back to
inventory/batches/movements/sales/bills.

Modules:
    inventory_intelligence   low-stock detection (configurable threshold)
    expiry_intelligence      expired / expiring-soon batches
    stock_intelligence       reconciliation discrepancy insights
    intelligence_service     aggregate store health report
    product_intelligence     AI-visible (class/product, camera) comparisons (M15)
    shelf_intelligence       AI-estimated shelf occupancy/states/misplacement (M15)
    misplacement             possible-misplacement candidates (M15)
    ai_summary               store AI digest for the dashboard (M15)

No YOLO/PaddleOCR/heavy AI imports. No ML. Insights are business intelligence
only, operating on already-persisted data. The M15 modules additionally operate
on ALREADY-PERSISTED observations (written by the Edge writer) — they never run
inference.
"""

from .inventory_intelligence import (
    InventoryIntelligence,
    LowStockInsight,
)
from .expiry_intelligence import (
    ExpiryIntelligence,
    ExpiryInsight,
    EXPIRY_STATUS_SAFE,
    EXPIRY_STATUS_EXPIRING_SOON,
    EXPIRY_STATUS_EXPIRED,
    EXPIRY_STATUS_MONTH,
    EXPIRY_STATUS_NO_DATE,
)
from .stock_intelligence import (
    StockDiscrepancyIntelligence,
    DiscrepancyInsight,
)
from .intelligence_service import IntelligenceService, InventoryHealth
from .product_intelligence import (
    ProductIntelligenceRow,
    ProductIntelligenceService,
    COMP_MATCH,
    COMP_SHORTAGE,
    COMP_SURPLUS,
    COMP_NO_INVENTORY,
    COMP_NOT_ASSESSED,
)
from .shelf_intelligence import (
    LOW_OCCUPANCY_FRACTION,
    SHELF_STATE_UNKNOWN,
    SHELF_STATE_EMPTY,
    SHELF_STATE_LOW,
    SHELF_STATE_NORMAL,
    ShelfIntelligenceRow,
    ShelfIntelligenceService,
    ShelfRegion,
    ShelfVisibleProduct,
    parse_shelf_regions,
)
from .misplacement import MisplacementRow, MisplacementService
from .ai_summary import (
    AISummary,
    AISummaryService,
    CameraSummary,
    PeopleSummary,
    ProductSummary,
    ShelfSummary,
    ReconciliationSummary,
)

__all__ = [
    "InventoryIntelligence",
    "LowStockInsight",
    "ExpiryIntelligence",
    "ExpiryInsight",
    "EXPIRY_STATUS_SAFE",
    "EXPIRY_STATUS_EXPIRING_SOON",
    "EXPIRY_STATUS_EXPIRED",
    "EXPIRY_STATUS_MONTH",
    "EXPIRY_STATUS_NO_DATE",
    "StockDiscrepancyIntelligence",
    "DiscrepancyInsight",
    "IntelligenceService",
    "InventoryHealth",
    "ProductIntelligenceRow",
    "ProductIntelligenceService",
    "COMP_MATCH",
    "COMP_SHORTAGE",
    "COMP_SURPLUS",
    "COMP_NO_INVENTORY",
    "COMP_NOT_ASSESSED",
    "LOW_OCCUPANCY_FRACTION",
    "SHELF_STATE_UNKNOWN",
    "SHELF_STATE_EMPTY",
    "SHELF_STATE_LOW",
    "SHELF_STATE_NORMAL",
    "ShelfIntelligenceRow",
    "ShelfIntelligenceService",
    "ShelfRegion",
    "ShelfVisibleProduct",
    "parse_shelf_regions",
    "MisplacementRow",
    "MisplacementService",
    "AISummary",
    "AISummaryService",
    "CameraSummary",
    "PeopleSummary",
    "ProductSummary",
    "ShelfSummary",
    "ReconciliationSummary",
]
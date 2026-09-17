"""Deterministic demo scenario catalog (M21).

Pure metadata + shared constants. No database access lives here so the catalog
can be imported by schemas, routers and the frontend contract without pulling
in the demo engine.

Every scenario is a DETERMINISTIC overlay applied on top of the M18 baseline
demo store after a full reset. Activation always starts from the same seeded
baseline, so the same scenario twice yields the same state and scenarios never
contaminate one another.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# --- scenario keys (stable contract, used by the API + frontend) -----------
SCENARIO_NORMAL = "NORMAL_STORE"
SCENARIO_LOW_STOCK = "LOW_STOCK"
SCENARIO_OUT_OF_STOCK = "OUT_OF_STOCK"
SCENARIO_EXPIRY_RISK = "EXPIRY_RISK"
SCENARIO_LOW_SHELF_BACKSTOCK = "LOW_SHELF_BACKSTOCK"
SCENARIO_MISPLACEMENT = "MISPLACEMENT"
SCENARIO_HIGH_TRAFFIC = "HIGH_TRAFFIC"
SCENARIO_HIGH_DWELL = "HIGH_DWELL"
SCENARIO_MULTI_CAMERA_JOURNEY = "MULTI_CAMERA_JOURNEY"
SCENARIO_CAMERA_OFFLINE = "CAMERA_OFFLINE"
SCENARIO_SMART_RECEIVING = "SMART_RECEIVING"
SCENARIO_COMBINED_CRISIS = "COMBINED_CRISIS"

DEFAULT_SCENARIO = SCENARIO_NORMAL


@dataclass(frozen=True)
class ScenarioInfo:
    """Presenter-facing description of one scenario."""

    key: str
    name: str
    description: str
    category: str
    expected: List[str] = field(default_factory=list)
    # Where the presenter should go to see the effect.
    focus_path: str = "/app/dashboard"


SCENARIOS: List[ScenarioInfo] = [
    ScenarioInfo(
        key=SCENARIO_NORMAL,
        name="Normal Store",
        description=(
            "Healthy baseline: stock above reorder levels, no urgent expiry, "
            "shelves normally occupied, every camera reporting."
        ),
        category="healthy",
        expected=[
            "Store health HEALTHY",
            "No HIGH/MEDIUM operational insights",
            "Cameras all healthy",
        ],
        focus_path="/app/dashboard",
    ),
    ScenarioInfo(
        key=SCENARIO_LOW_STOCK,
        name="Low Stock",
        description=(
            "A fast-moving product falls to or below its reorder level while "
            "still having stock on hand."
        ),
        category="inventory",
        expected=[
            "LOW_STOCK insight (MEDIUM)",
            "Store health ATTENTION",
            "Recommended action: review replenishment",
        ],
        focus_path="/app/insights",
    ),
    ScenarioInfo(
        key=SCENARIO_OUT_OF_STOCK,
        name="Out of Stock",
        description="A product's on-hand quantity reaches zero.",
        category="inventory",
        expected=[
            "OUT_OF_STOCK insight (HIGH)",
            "SHORTAGE alert",
            "Store health CRITICAL",
        ],
        focus_path="/app/insights",
    ),
    ScenarioInfo(
        key=SCENARIO_EXPIRY_RISK,
        name="Expiry Risk",
        description=(
            "One confirmed batch is within the expiring-soon window and one "
            "batch is already past its expiry date."
        ),
        category="expiry",
        expected=[
            "EXPIRY_RISK insight (MEDIUM)",
            "EXPIRED_BATCH insight (HIGH)",
            "EXPIRY alerts",
        ],
        focus_path="/app/insights",
    ),
    ScenarioInfo(
        key=SCENARIO_LOW_SHELF_BACKSTOCK,
        name="Low Shelf + Back Stock",
        description=(
            "There is plenty of inventory, but the shelf's AI-estimated visible "
            "occupancy is low — a stocking/rotation problem, not a supply one."
        ),
        category="shelf",
        expected=[
            "LOW_SHELF_AVAILABILITY insight (MEDIUM)",
            "Recommended action: replenish the shelf",
            "No out-of-stock insight (inventory is available)",
        ],
        focus_path="/app/insights",
    ),
    ScenarioInfo(
        key=SCENARIO_MISPLACEMENT,
        name="Possible Misplacement",
        description=(
            "AI detects a mapped product on a shelf whose planogram expects "
            "other products. Reported as POSSIBLE, never as certainty."
        ),
        category="shelf",
        expected=[
            "MISPLACEMENT insight (LOW)",
            "MISPLACEMENT alert (if configured)",
        ],
        focus_path="/app/shelf-intelligence",
    ),
    ScenarioInfo(
        key=SCENARIO_HIGH_TRAFFIC,
        name="High Traffic Zone",
        description=(
            "Deterministic anonymous zone visits push one zone well above the "
            "configured traffic floor."
        ),
        category="customer_flow",
        expected=[
            "HIGH_TRAFFIC_ZONE insight (INFO)",
            "Highest observed traffic shown on the dashboard",
        ],
        focus_path="/app/journeys",
    ),
    ScenarioInfo(
        key=SCENARIO_HIGH_DWELL,
        name="High Dwell Zone",
        description=(
            "Several closed anonymous visits in one zone have an average dwell "
            "above the configured floor."
        ),
        category="customer_flow",
        expected=[
            "HIGH_DWELL_ZONE insight (INFO)",
            "Highest observed dwell shown on the dashboard",
        ],
        focus_path="/app/journeys",
    ),
    ScenarioInfo(
        key=SCENARIO_MULTI_CAMERA_JOURNEY,
        name="Multi-Camera Journey",
        description=(
            "One anonymous global person is observed across the entrance, "
            "aisle and till cameras with camera transitions."
        ),
        category="customer_flow",
        expected=[
            "Anonymous Person timeline across 3 cameras",
            "Zone dwell + camera transitions",
            "No faces / embeddings exposed",
        ],
        focus_path="/app/journeys",
    ),
    ScenarioInfo(
        key=SCENARIO_CAMERA_OFFLINE,
        name="Camera Offline",
        description=(
            "One demo camera stops producing observations (simulated heartbeat "
            "proxy) while the others keep reporting."
        ),
        category="camera",
        expected=[
            "CAMERA_HEALTH insight (HIGH)",
            "CAMERA_OFFLINE alert",
            "Store health CRITICAL",
        ],
        focus_path="/app/insights",
    ),
    ScenarioInfo(
        key=SCENARIO_SMART_RECEIVING,
        name="Smart Batch Receiving",
        description=(
            "Baseline restored so the presenter can run the REAL M17 close-up "
            "scan workflow (barcode + OCR + human confirmation)."
        ),
        category="receiving",
        expected=[
            "Real M17 scan/review/confirm workflow",
            "Atomic BatchService + InventoryService commit",
        ],
        focus_path="/app/receive",
    ),
    ScenarioInfo(
        key=SCENARIO_COMBINED_CRISIS,
        name="Combined Store Crisis",
        description=(
            "Several independent problems at once — low stock, expiry, low "
            "shelf occupancy, possible misplacement and a camera offline."
        ),
        category="crisis",
        expected=[
            "Store health ATTENTION/CRITICAL",
            "Multiple insights across categories",
            "Multiple alerts in the Alerts Center",
        ],
        focus_path="/app/dashboard",
    ),
]

SCENARIOS_BY_KEY = {s.key: s for s in SCENARIOS}
VALID_SCENARIO_KEYS = tuple(SCENARIOS_BY_KEY.keys())

# --- deterministic shelf-region observation plan used by neutralisation ----
# One NORMAL_VISIBLE observation per configured region. (class, bbox, track).
# Bboxes are chosen so the region occupancy fraction is comfortably >= 0.35
# (the LOW_OCCUPANCY_FRACTION threshold) and the class is on-planogram where
# the shelf has an expectation, so no misplacement is fabricated.
NEUTRAL_SHELF_OBSERVATIONS = [
    ("A1", "ParleG", [10, 16, 90, 34], 9001),
    ("A2", "Maggi", [10, 40, 90, 54], 9002),
    ("B1", "TataSalt", [10, 58, 90, 72], 9003),
    ("B2", "AmulMilk", [10, 78, 90, 96], 9004),
    ("E1", "Maggi", [10, 2, 90, 12], 9005),
]

# Low-shelf (LOW_SHELF_BACKSTOCK) plan for shelf A2 only.
LOW_SHELF_OBSERVATIONS = [
    ("A2", "Maggi", [70, 42, 76, 52], 9102),
]

# Misplacement plan: Maggi (mapped, ai_classes=["Maggi"]) on shelf B2 whose
# planogram expects AmulMilk / Coca-Cola. Bbox keeps B2 NORMAL_VISIBLE.
MISPLACEMENT_OBSERVATIONS = [
    ("B2", "Maggi", [30, 80, 40, 94], 9202),
]

# Customer-flow scenarios insert deterministic aggregate zone visits.
HIGH_TRAFFIC_VISIT_COUNT = 64
HIGH_TRAFFIC_DWELL_SECONDS = 25.0
HIGH_DWELL_VISIT_COUNT = 8
HIGH_DWELL_DWELL_SECONDS = 300.0

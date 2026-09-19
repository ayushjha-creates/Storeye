"""Milestone 15 tests: Product & Shelf Intelligence.

Integration tests against the isolated storeye_test database. Verify the
intelligence services operate on REAL Edge AI observations, honour camera
scoping, use the shared counting strategy, surface AI vs inventory differences
informationally, mark misplacement only with explicit expectations, and NEVER
mutate inventory/movements/batches/bills/sales.

Also covers the Edge ObservationWriter's EXPLICIT class->product enrichment
and the `class_name` observation filter.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    Batch,
    Bill,
    Camera,
    Inventory,
    InventoryMovement,
    Observation,
    OBS_PRODUCT,
    Planogram,
    PlanogramItem,
    Product,
    Sale,
    Shelf,
    Store,
    Zone,
)
from app.services.intelligence import (
    COMP_NO_INVENTORY,
    COMP_NOT_ASSESSED,
    COMP_MATCH,
    COMP_SHORTAGE,
    COMP_SURPLUS,
    AISummaryService,
    MisplacementService,
    ProductIntelligenceService,
    SHELF_STATE_EMPTY,
    SHELF_STATE_LOW,
    SHELF_STATE_NORMAL,
    SHELF_STATE_UNKNOWN,
    ShelfIntelligenceService,
    parse_shelf_regions,
)
from app.services.observations import ObservationService

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://storeye@localhost:5433/storeye_test")

BASE = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine):
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def store(db) -> Store:
    s = Store(name="Intel Store", timezone="Asia/Kolkata")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def zone(db, store) -> Zone:
    z = Zone(store_id=store.id, name="Snacks")
    db.add(z)
    db.commit()
    db.refresh(z)
    return z


@pytest.fixture()
def shelf(db, store, zone) -> Shelf:
    s = Shelf(store_id=store.id, zone_id=zone.id, code="A1")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def camera(db, store) -> Camera:
    c = Camera(
        name="shelf-cam-1",
        store_id=store.id,
        config={
            "shelf_regions": [
                {"code": "A1", "label": "Aisle A top", "bbox": [0, 0, 100, 100]},
                {"code": "B2", "bbox": [200, 0, 300, 100]},
            ]
        },
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture()
def product(db, store) -> Product:
    p = Product(store_id=store.id, sku="INT-LAYS", name="Lays", selling_price=10, ai_classes=["Lays"])
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def mapped_product(db, store) -> Product:
    p = Product(store_id=store.id, sku="INT-MAGGI", name="Maggi", selling_price=14, ai_classes=["Maggi"])
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _record_product(db, store, camera, class_name, *, bbox, conf=0.9, frame=0, observed_at=None, product_id=None):
    return ObservationService(db).record_product_observation(
        store_id=store.id,
        camera_id=camera.id,
        product_id=product_id,
        confidence=conf,
        bbox=bbox,
        frame_number=frame,
        observed_at=observed_at or _now(),
        details={"class_name": class_name},
    )


def _set_inventory(db, store, product, qty):
    inv = db.scalar(select(Inventory).where(Inventory.store_id == store.id, Inventory.product_id == product.id))
    if inv is None:
        inv = Inventory(store_id=store.id, product_id=product.id, quantity=qty)
    else:
        inv.quantity = qty
    db.add(inv)
    db.commit()
    return inv


def _activate_planogram(db, store, shelf, *product_tuples):
    """product_tuples: (product, expected_facings)."""
    pl = Planogram(store_id=store.id, name="Active", is_active=True)
    db.add(pl)
    db.flush()
    for p, facings in product_tuples:
        db.add(PlanogramItem(planogram_id=pl.id, shelf_id=shelf.id, product_id=p.id, expected_facings=facings))
    db.commit()
    return pl


def _count(db, model):
    return db.query(model).count()


# ---------------------------------------------------------------------------
# 1. Shared counting strategy on product intelligence
# ---------------------------------------------------------------------------
def test_product_intelligence_uses_shared_counting(db, store, product, camera):
    _set_inventory(db, store, product, 3)
    # 3 distinct instances in one frame (region A1), class "Lays" -> mapped.
    for k in range(3):
        _record_product(db, store, camera, "Lays", product_id=product.id,
                        bbox=[k * 30, 0, k * 30 + 20, 20], frame=0)
    rows = ProductIntelligenceService(db).products(store_id=store.id)
    assert len(rows) == 1
    r = rows[0]
    assert r.ai_class == "Lays"
    assert r.mapped and r.product_id == product.id
    assert r.visible_count == 3
    assert r.counting_rule == "max_simultaneous_per_frame"
    assert r.comparison_status == COMP_MATCH
    assert r.database_quantity == 3 and r.difference == 0


# ---------------------------------------------------------------------------
# 2. Mapped product with lower visible -> POSSIBLE_SHORTAGE (informational)
# ---------------------------------------------------------------------------
def test_product_intelligence_possible_shortage(db, store, product, camera):
    _set_inventory(db, store, product, 5)
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[0, 0, 20, 20])
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[30, 0, 50, 20])
    rows = ProductIntelligenceService(db).products(store_id=store.id)
    r = rows[0]
    assert r.comparison_status == COMP_SHORTAGE
    assert r.database_quantity == 5 and r.visible_count == 2 and r.difference == -3


# ---------------------------------------------------------------------------
# 3. Mapped product with higher visible -> POSSIBLE_SURPLUS (informational)
# ---------------------------------------------------------------------------
def test_product_intelligence_possible_surplus(db, store, product, camera):
    _set_inventory(db, store, product, 2)
    for k in range(8):
        _record_product(db, store, camera, "Lays", product_id=product.id,
                        bbox=[k * 30, 0, k * 30 + 20, 20], frame=0)
    r = ProductIntelligenceService(db).products(store_id=store.id)[0]
    assert r.comparison_status == COMP_SURPLUS
    assert r.visible_count == 8 and r.difference == 6


# ---------------------------------------------------------------------------
# 4. Mapped product with NO inventory record -> NO_INVENTORY
# ---------------------------------------------------------------------------
def test_product_intelligence_no_inventory(db, store, product, camera):
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[0, 0, 20, 20])
    r = ProductIntelligenceService(db).products(store_id=store.id)[0]
    assert r.comparison_status == COMP_NO_INVENTORY
    assert r.database_quantity is None and r.difference is None


# ---------------------------------------------------------------------------
# 5. Unmapped AI class -> NOT_ASSESSED + "Unmapped AI class" messaging
# ---------------------------------------------------------------------------
def test_product_intelligence_unmapped_class(db, store, camera):
    _record_product(db, store, camera, "CocaCola", bbox=[0, 0, 20, 20])
    _record_product(db, store, camera, "SastaThing", bbox=[30, 0, 50, 20])
    rows = ProductIntelligenceService(db).products(store_id=store.id)
    assert len(rows) == 2
    assert all(not r.mapped for r in rows)
    assert all(r.comparison_status == COMP_NOT_ASSESSED for r in rows)
    assert any("Unknown product" in (r.message or "") for r in rows)
    assert all(r.product_id is None for r in rows)


# ---------------------------------------------------------------------------
# 6. Camera scoping: no cross-camera fusion
# ---------------------------------------------------------------------------
def test_product_intelligence_camera_scope(db, store, product):
    cam1 = Camera(name="c1", store_id=store.id, config={"shelf_regions": [{"code": "A1", "bbox": [0, 0, 100, 100]}]})
    cam2 = Camera(name="c2", store_id=store.id, config={"shelf_regions": [{"code": "A1", "bbox": [0, 0, 100, 100]}]})
    db.add_all([cam1, cam2]); db.commit(); db.refresh(cam1); db.refresh(cam2)
    _record_product(db, store, cam1, "Lays", product_id=product.id, bbox=[0, 0, 20, 20])
    _record_product(db, store, cam2, "Lays", product_id=product.id, bbox=[0, 0, 20, 20])
    svc = ProductIntelligenceService(db)
    rows = svc.products(store_id=store.id)
    by_cam = {r.camera_id: r for r in rows}
    assert len(rows) == 2
    assert by_cam[cam1.id].visible_count == 1
    assert by_cam[cam2.id].visible_count == 1
    only = svc.products(store_id=store.id, camera_id=cam1.id)
    assert len(only) == 1 and only[0].camera_id == cam1.id


# ---------------------------------------------------------------------------
# 7. class_name filter on ObservationService + observer query
# ---------------------------------------------------------------------------
def test_class_name_observation_filter(db, store, camera):
    _record_product(db, store, camera, "Lays", bbox=[0, 0, 20, 20])
    _record_product(db, store, camera, "Maggi", bbox=[30, 0, 50, 20])
    svc = ObservationService(db)
    items, total = svc.query_observations(store_id=store.id, class_name="Lays")
    assert total == 1 and all((o.details or {}).get("class_name") == "Lays" for o in items)
    items2, total2 = svc.query_observations(store_id=store.id, class_name="Maggi")
    assert total2 == 1 and all((o.details or {}).get("class_name") == "Maggi" for o in items2)
    _, total_absent = svc.query_observations(store_id=store.id, class_name="Nope")
    assert total_absent == 0
    summary = svc.observation_summary(store_id=store.id, class_name="Lays")
    assert summary["by_type"].get("PRODUCT") == 1


# ---------------------------------------------------------------------------
# 8. Shelf: geometric association (bbox-center in region) + occupancy
# ---------------------------------------------------------------------------
def test_shelf_geometric_association_and_occupancy(db, store, product, shelf, camera):
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[10, 10, 60, 60])  # A1
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[240, 10, 290, 60])  # B2
    rows = ShelfIntelligenceService(db).shelves(store_id=store.id)
    by_code = {r.shelf_code: r for r in rows}
    assert set(by_code) == {"A1", "B2"}
    # A1 occupancy includes only the A1-region product (~ area 50x50 / 100x100).
    a1 = by_code["A1"]
    assert a1.detection_status in (SHELF_STATE_LOW, SHELF_STATE_NORMAL)
    assert 0.0 < a1.estimated_visible_occupancy <= 0.5
    assert a1.shelf_id == shelf.id and a1.zone_name == "Snacks"
    assert len(a1.visible_products) == 1 and a1.visible_products[0].ai_class == "Lays"
    b2 = by_code["B2"]
    assert 0.0 < b2.estimated_visible_occupancy <= 0.5


# ---------------------------------------------------------------------------
# 9. Shelf UNKNOWN when camera has no AI data for the window
# ---------------------------------------------------------------------------
def test_shelf_unknown_no_ai_data(db, store, camera):
    rows = ShelfIntelligenceService(db).shelves(store_id=store.id)
    assert rows
    assert all(r.detection_status == SHELF_STATE_UNKNOWN for r in rows)
    assert all(r.estimated_visible_occupancy is None for r in rows)
    assert any("No AI data" in (r.last_analysis_message or "") for r in rows)


# ---------------------------------------------------------------------------
# 10. Shelf LOW_VISIBLE at low occupancy fraction
# ---------------------------------------------------------------------------
def test_shelf_low_visible(db, store, product, camera):
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[10, 10, 30, 20])  # small in A1
    a1 = {r.shelf_code: r for r in ShelfIntelligenceService(db).shelves(store_id=store.id)}["A1"]
    assert a1.detection_status == SHELF_STATE_LOW
    assert a1.refill_recommended is True


def test_shelf_half_full_recommends_refill(db, store, product, camera):
    # A1 region is 100x100; a 50x100 product covers exactly half.
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[0, 0, 50, 100])
    a1 = {r.shelf_code: r for r in ShelfIntelligenceService(db).shelves(store_id=store.id)}["A1"]
    assert a1.estimated_visible_occupancy == 0.5
    assert a1.detection_status == SHELF_STATE_LOW  # half full or less
    assert a1.refill_recommended is True


def test_shelf_normal_visible_is_deterministic(db, store, product, camera):
    # A large, well-centred product in A1 gives a high visible occupancy.
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[0, 0, 80, 80])
    first = {r.shelf_code: r for r in ShelfIntelligenceService(db).shelves(store_id=store.id)}["A1"]
    second = {r.shelf_code: r for r in ShelfIntelligenceService(db).shelves(store_id=store.id)}["A1"]
    assert first.detection_status == SHELF_STATE_NORMAL
    assert first.refill_recommended is False
    # Repeated reads are stable: same status, same estimate, same method.
    assert second.detection_status == SHELF_STATE_NORMAL
    assert second.estimated_visible_occupancy == first.estimated_visible_occupancy
    assert second.occupancy_method == first.occupancy_method


# ---------------------------------------------------------------------------
# 11. Shelf EMPTY_VISIBLE when camera has data but region has none
# ---------------------------------------------------------------------------
def test_shelf_empty_visible(db, store, product, camera):
    # Camera has AI data but only in region A1; B2 stays empty.
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[10, 10, 60, 60])
    by_code = {r.shelf_code: r for r in ShelfIntelligenceService(db).shelves(store_id=store.id)}
    assert by_code["B2"].detection_status == SHELF_STATE_EMPTY
    assert by_code["B2"].estimated_visible_occupancy == 0.0
    assert by_code["B2"].refill_recommended is True
    assert "no visible product" in (by_code["B2"].last_analysis_message or "")
    assert by_code["A1"].detection_status != SHELF_STATE_EMPTY


# ---------------------------------------------------------------------------
# 12. Misplacement: only mapped + expected-exclusion -> POSSIBLE_MISPLACEMENT
# ---------------------------------------------------------------------------
def test_misplacement_mapped_on_shelf_expecting_other(db, store, product, mapped_product, shelf, camera):
    # Planogram expects only Maggi on shelf A1.
    _activate_planogram(db, store, shelf, (mapped_product, 2))
    # Shelf sees BOTH mapped Lays (not expected -> misplaced) and Maggi (expected).
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[10, 10, 60, 60])
    _record_product(db, store, camera, "Maggi", product_id=mapped_product.id, bbox=[30, 30, 80, 80])
    by_code = {r.shelf_code: r for r in ShelfIntelligenceService(db).shelves(store_id=store.id)}["A1"]
    prods = {p.ai_class: p for p in by_code.visible_products}
    assert prods["Lays"].possible_misplacement is True
    assert prods["Lays"].expected_on_shelf is False
    assert prods["Maggi"].possible_misplacement is False
    assert prods["Maggi"].expected_on_shelf is True
    mis = MisplacementService(db).misplacements(store_id=store.id)
    assert len(mis) == 1 and mis[0].ai_class == "Lays" and mis[0].shelf_code == "A1"


# ---------------------------------------------------------------------------
# 13. Misplacement: unmapped classes NEVER flagged
# ---------------------------------------------------------------------------
def test_misplacement_unmapped_not_flagged(db, store, mapped_product, shelf, camera):
    _activate_planogram(db, store, shelf, (mapped_product, 2))
    # Unmapped class on shelf A1 -> cannot assess -> NOT a misplacement.
    _record_product(db, store, camera, "CocaCola", bbox=[10, 10, 60, 60])
    by_code = {r.shelf_code: r for r in ShelfIntelligenceService(db).shelves(store_id=store.id)}["A1"]
    assert by_code.visible_products[0].possible_misplacement is False
    assert MisplacementService(db).misplacements(store_id=store.id) == []


# ---------------------------------------------------------------------------
# 14. Misplacement: shelf with NO planogram expectation -> nothing flagged
# ---------------------------------------------------------------------------
def test_misplacement_no_expectation_not_flagged(db, store, product, camera):
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[10, 10, 60, 60])
    assert MisplacementService(db).misplacements(store_id=store.id) == []


# ---------------------------------------------------------------------------
# 15. Confidence floor: low-confidence detections ignored
# ---------------------------------------------------------------------------
def test_intelligence_confidence_floor(db, store, product, camera):
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[0, 0, 20, 20], conf=0.95)  # counts
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[30, 0, 50, 20], conf=0.1)  # ignored
    r = ProductIntelligenceService(db).products(store_id=store.id, min_confidence=0.5)[0]
    assert r.visible_count == 1


# ---------------------------------------------------------------------------
# 16. Temporal window: only observations inside window count
# ---------------------------------------------------------------------------
def test_intelligence_temporal_window(db, store, product, camera):
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[0, 0, 20, 20], observed_at=_now())
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[30, 0, 50, 20],
                    observed_at=_now() - timedelta(days=10))
    r = ProductIntelligenceService(db).products(store_id=store.id, hours=24)[0]
    assert r.visible_count == 1  # only the recent one


# ---------------------------------------------------------------------------
# 17. MANDATORY: intelligence never mutates inventory/movements/batches/bills/sales
# ---------------------------------------------------------------------------
def test_intelligence_no_mutation(db, store, product, mapped_product, shelf, camera):
    _set_inventory(db, store, product, 2)
    _activate_planogram(db, store, shelf, (mapped_product, 2))
    for k in range(9):
        _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[k * 10, 0, k * 10 + 5, 10])
    before = {
        "inventory": _count(db, Inventory),
        "movements": _count(db, InventoryMovement),
        "batches": _count(db, Batch),
        "sales": _count(db, Sale),
        "bills": _count(db, Bill),
    }
    ProductIntelligenceService(db).products(store_id=store.id)
    ShelfIntelligenceService(db).shelves(store_id=store.id)
    MisplacementService(db).misplacements(store_id=store.id)
    AISummaryService(db).summary(store_id=store.id)
    after = {
        "inventory": _count(db, Inventory),
        "movements": _count(db, InventoryMovement),
        "batches": _count(db, Batch),
        "sales": _count(db, Sale),
        "bills": _count(db, Bill),
    }
    assert before == after


# ---------------------------------------------------------------------------
# 18. AISummary aggregates consistently (informational digests)
# ---------------------------------------------------------------------------
def test_ai_summary_digest(db, store, product, mapped_product, shelf, camera):
    _activate_planogram(db, store, shelf, (mapped_product, 2))
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[10, 10, 60, 60])
    _record_product(db, store, camera, "Maggi", product_id=mapped_product.id, bbox=[30, 30, 80, 80])
    s = AISummaryService(db).summary(store_id=store.id)
    assert s.cameras.total == 1 and s.cameras.ai_running == 1 and s.cameras.ai_stopped == 0
    assert s.cameras.regions_configured == 1  # only camera with shelf_regions
    assert s.products.visible_classes == 2
    assert s.products.mapped_classes == 2 and s.products.unmapped_classes == 0
    assert s.products.total_visible_quantity == 2
    assert s.shelves.regions_configured == 2
    assert s.shelves.with_ai_data == 2
    assert s.shelves.possible_misplacements == 1


# ---------------------------------------------------------------------------
# 19. parse_shelf_regions validation
# ---------------------------------------------------------------------------
def test_parse_shelf_regions_validation(db, store):
    bad = Camera(name="bad", store_id=store.id, config={
        "shelf_regions": [
            {"code": "A1", "bbox": [0, 0, 100, 100]},
            {"code": "BAD", "bbox": [0, 0, 0, 10]},  # zero area -> skipped
            "not-a-dict",
            {"bbox": [0, 0, 10, 10]},  # no code -> skipped
            {"code": "BAD2", "bbox": [0, 0, 10, 5]},  # missing bbox-> area ok but this stays? no, bbox present; keep valid
            {"code": "A2", "bbox": [0, 0, 50, 50]},
        ]
    })
    regions = parse_shelf_regions(bad)
    codes = [r.code for r in regions]
    assert codes == ["A1", "BAD2", "A2"]
    assert regions[0].bbox == [0, 0, 100, 100]


# ---------------------------------------------------------------------------
# 20. PRODUCT_CANDIDATE path: only unmapped detections, never guessed
# ---------------------------------------------------------------------------
def test_product_candidates_only_unmapped(db, store, product, mapped_product, camera):
    _record_product(db, store, camera, "Lays", product_id=product.id, bbox=[0, 0, 20, 20])
    _record_product(db, store, camera, "CocaCola", bbox=[30, 0, 50, 20])
    cands = ProductIntelligenceService(db).candidates(store_id=store.id)
    assert len(cands) == 1
    assert cands[0].ai_class == "CocaCola"
    assert cands[0].mapped is False
    assert cands[0].product_id is None
    assert "Unknown product" in (cands[0].message or "")
    # A mapped detection is never a candidate.
    assert all(c.ai_class != "Lays" for c in cands)


def test_product_candidates_camera_scope(db, store, product):
    cam1 = Camera(name="c1", store_id=store.id)
    cam2 = Camera(name="c2", store_id=store.id)
    db.add_all([cam1, cam2]); db.commit(); db.refresh(cam1); db.refresh(cam2)
    _record_product(db, store, cam1, "CocaCola", bbox=[0, 0, 20, 20])
    _record_product(db, store, cam2, "Sprite", bbox=[0, 0, 20, 20])
    svc = ProductIntelligenceService(db)
    assert len(svc.candidates(store_id=store.id)) == 2
    only = svc.candidates(store_id=store.id, camera_id=cam1.id)
    assert len(only) == 1 and only[0].ai_class == "CocaCola"


# ---------------------------------------------------------------------------
# 21. Shelf temporal smoothing: a single detection spike is ignored
# ---------------------------------------------------------------------------
def test_shelf_temporal_smoothing_ignores_single_spike(db, store, product, camera):
    now = _now()
    # Three quiet minute-buckets (small 10x10 box = 1% occupancy each)...
    for i in range(3):
        _record_product(
            db, store, camera, "Lays", product_id=product.id,
            bbox=[0, 0, 10, 10], frame=i,
            observed_at=now - timedelta(minutes=4 - i),
        )
    # ...plus one spike bucket where the whole region is covered.
    _record_product(
        db, store, camera, "Lays", product_id=product.id,
        bbox=[0, 0, 100, 100], frame=99,
        observed_at=now - timedelta(minutes=1),
    )
    a1 = {r.shelf_code: r for r in ShelfIntelligenceService(db).shelves(store_id=store.id)}["A1"]
    # Raw whole-window occupancy would be ~1.0; the median ignores the spike.
    assert a1.occupancy_method == "median_60s"
    assert a1.occupancy_samples == 4
    assert a1.estimated_visible_occupancy is not None
    assert a1.estimated_visible_occupancy < 0.5
    assert a1.detection_status != SHELF_STATE_NORMAL


def test_shelf_smoothing_falls_back_to_raw_with_few_buckets(db, store, product, camera):
    now = _now()
    for i in range(4):
        _record_product(
            db, store, camera, "Lays", product_id=product.id,
            bbox=[0, 0, 20, 20], frame=i,
            observed_at=now - timedelta(seconds=1),
        )
    a1 = {r.shelf_code: r for r in ShelfIntelligenceService(db).shelves(store_id=store.id)}["A1"]
    # All observations share one minute-bucket -> not enough data to smooth.
    assert a1.occupancy_method == "raw"
    assert a1.occupancy_samples == 1
    assert a1.estimated_visible_occupancy is not None


# ---------------------------------------------------------------------------
# Real-AI smoke (marked) - only runs when explicitly selected
# ---------------------------------------------------------------------------
@pytest.mark.real_ai
def test_real_shelf_product_smoke():
    """Real ShelfDetector finds at least one product across the shelf dataset."""
    import cv2

    from app.edge.models.product_detector import ProductDetectorModel

    images_dir = os.path.join(REPO_ROOT, "data/datasets/shelves/images")
    if not os.path.exists(images_dir):
        pytest.skip("shelf dataset not present")
    import glob

    images = sorted(glob.glob(os.path.join(images_dir, "*.jpeg")) + glob.glob(os.path.join(images_dir, "*.jpg")))
    if not images:
        pytest.skip("no shelf images present")

    model = ProductDetectorModel()
    if not model.initialized:
        pytest.skip("real shelf weights not present")

    found = []
    for path in images[:8]:
        frame = cv2.imread(path)
        frame = cv2.resize(frame, (1280, 720))
        found.extend(model.detect_frame(frame))

    high_conf = [d for d in found if d.confidence >= 0.25 and d.class_name]
    assert high_conf, f"no product detections across {len(images)} shelf images"

    best = max(found, key=lambda d: d.confidence)
    assert best.class_name
    assert best.confidence >= 0.25
    assert len(best.bbox_xyxy) == 4
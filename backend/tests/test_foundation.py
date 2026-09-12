from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.core.config import get_settings
from app.core.database import (
    generate_uuid,
    utcnow,
    SyncStatus,
    init_db,
    get_session,
    Store,
    Camera,
    Zone,
    Product,
    Planogram,
    InventoryLedger,
    VisualEvent,
    QueueMetric,
    ReplenishmentTask,
    Recommendation,
    User,
)

# Legacy SQLite/SQLModel diagnostics stack (app.core.database): these tests
# intentionally exercise the legacy stack that backs /api/health, /api/ready
# and /api/metrics. They are NOT production business-path tests.
pytestmark = pytest.mark.legacy_sqlite


class TestUUIDGeneration:
    def test_uuid_is_valid_format(self):
        uid = generate_uuid()
        parsed = uuid.UUID(uid)
        assert str(parsed) == uid

    def test_uuids_are_unique(self):
        ids = {generate_uuid() for _ in range(500)}
        assert len(ids) == 500


class TestUtcnow:
    def test_returns_utc(self):
        now = utcnow()
        assert now.tzinfo == timezone.utc

    def test_returns_recent_time(self):
        before = datetime.now(timezone.utc)
        now = utcnow()
        after = datetime.now(timezone.utc)
        assert before <= now <= after


class TestSyncStatus:
    def test_values(self):
        assert SyncStatus.PENDING.value == "PENDING"
        assert SyncStatus.SYNCED.value == "SYNCED"
        assert SyncStatus.FAILED.value == "FAILED"


class TestDatabaseInit:
    def test_init_creates_db_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGERETAIL_DATA_DIR", str(tmp_path))
        from app.core.config import get_settings
        get_settings.cache_clear()
        init_db()
        assert (tmp_path / "edgeretail.db").exists()

    def test_session_returns_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGERETAIL_DATA_DIR", str(tmp_path))
        from app.core.config import get_settings
        get_settings.cache_clear()
        init_db()
        session = get_session()
        assert session is not None


class TestModels:
    def _init(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGERETAIL_DATA_DIR", str(tmp_path))
        from app.core.config import get_settings
        get_settings.cache_clear()
        init_db()

    def test_store_crud(self, tmp_path, monkeypatch):
        self._init(tmp_path, monkeypatch)
        session = get_session()
        store = Store(name="Test Store", address="Mumbai")
        session.add(store)
        session.commit()
        session.refresh(store)
        assert store.id
        assert store.name == "Test Store"
        assert store.sync_status == SyncStatus.PENDING.value
        session.delete(store)
        session.commit()

    def test_product_crud(self, tmp_path, monkeypatch):
        self._init(tmp_path, monkeypatch)
        session = get_session()
        sid = generate_uuid()
        product = Product(store_id=sid, sku="MAGGI-100", name="Maggi", price=12.0)
        session.add(product)
        session.commit()
        session.refresh(product)
        assert product.id
        assert product.sku == "MAGGI-100"
        session.delete(product)
        session.commit()

    def test_visual_event_has_event_type(self, tmp_path, monkeypatch):
        self._init(tmp_path, monkeypatch)
        session = get_session()
        event = VisualEvent(
            store_id=generate_uuid(),
            camera_id=generate_uuid(),
            zone_id=generate_uuid(),
            event_type="shelf_gap",
            confidence=0.95,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        assert event.event_type == "shelf_gap"
        session.delete(event)
        session.commit()

    def test_replenishment_task_priority_fields(self, tmp_path, monkeypatch):
        self._init(tmp_path, monkeypatch)
        session = get_session()
        task = ReplenishmentTask(
            store_id=generate_uuid(),
            product_id=generate_uuid(),
            priority_score=85.0,
            urgency=90.0,
            revenue_impact=2840.0,
            customer_impact=70.0,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        assert task.priority_score == 85.0
        assert task.revenue_impact == 2840.0
        session.delete(task)
        session.commit()

    def test_all_uuid_primary_keys(self, tmp_path, monkeypatch):
        self._init(tmp_path, monkeypatch)
        session = get_session()
        models = [
            Store(name="S"),
            Camera(store_id="c", name="C"),
            Zone(store_id="z", name="Z"),
            Product(store_id="p", sku="P", name="P"),
            Planogram(store_id="p", zone_id="z", product_id="p"),
            InventoryLedger(store_id="i", product_id="p"),
            VisualEvent(store_id="v", camera_id="c", zone_id="z", event_type="test"),
            QueueMetric(store_id="q", zone_id="z"),
            ReplenishmentTask(store_id="r", product_id="p"),
            Recommendation(store_id="r"),
            User(store_id="u", name="U"),
        ]
        for m in models:
            session.add(m)
        session.commit()
        for m in models:
            session.refresh(m)
            assert isinstance(m.id, str)
            assert len(m.id) == 36  # UUID4 length
        for m in models:
            session.delete(m)
        session.commit()

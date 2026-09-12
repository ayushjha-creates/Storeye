from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import SQLModel, Field, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from .config import get_settings
from .logging import get_logger

logger = get_logger(__name__)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SyncStatus(str, Enum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Base model for all syncable entities
# ---------------------------------------------------------------------------

class TimestampMixin:
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)


class SyncableMixin(TimestampMixin):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


# ---------------------------------------------------------------------------
# Core domain tables
# ---------------------------------------------------------------------------

class Store(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    name: str
    address: str = ""
    timezone: str = "Asia/Kolkata"
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class Camera(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    name: str
    source_type: str = "usb"  # usb | rtsp | video_file
    source_path: str = ""
    fps: int = 15
    is_active: bool = True
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class Zone(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    name: str
    zone_type: str = "shelf"  # shelf | entrance | queue | billing | general
    camera_id: str = Field(default="", index=True)
    roi_polygon: str = "[]"  # JSON-encoded list of (x,y) tuples
    sort_order: int = 0
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class Product(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    sku: str = Field(index=True)
    name: str
    category: str = ""
    price: float = 0.0
    unit: str = "unit"
    supplier: str = ""
    lead_time_hours: float = 24.0
    safety_stock: int = 5
    daily_sales_avg: float = 0.0
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class Planogram(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    zone_id: str = Field(index=True)
    product_id: str = Field(index=True)
    expected_facings: int = 1
    shelf_position: int = 0
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class InventoryLedger(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    product_id: str = Field(index=True)
    zone_id: str = Field(default="", index=True)
    shelf_stock: int = 0
    backroom_stock: int = 0
    last_counted_utc: datetime = Field(default_factory=utcnow)
    source: str = "manual"  # manual | camera | pos
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class VisualEvent(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    camera_id: str = Field(index=True)
    zone_id: str = Field(index=True)
    event_type: str = Field(index=True)  # shelf_gap | person_detected | queue_update | ...
    product_id: str = Field(default="", index=True)
    confidence: float = 0.0
    metadata_json: str = "{}"
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class QueueMetric(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    zone_id: str = Field(index=True)
    camera_id: str = Field(default="")
    queue_count: int = 0
    estimated_wait_sec: float = 0.0
    avg_service_time_sec: float = 120.0
    counters_open: int = 1
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class ReplenishmentTask(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    product_id: str = Field(index=True)
    zone_id: str = Field(default="")
    task_type: str = "replenishment"  # replenishment | procurement | rearrange
    status: str = "PENDING"  # PENDING | CONFIRMED | IN_PROGRESS | COMPLETED | CANCELLED
    priority_score: float = 0.0
    urgency: float = 0.0
    revenue_impact: float = 0.0
    customer_impact: float = 0.0
    recommendation_id: str = ""
    assigned_to: str = ""
    confirmed_by: str = ""
    completed_at_utc: Optional[datetime] = None
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class Recommendation(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    recommendation_type: str = ""  # replenishment | procurement | staffing | counter | ...
    action: str = ""
    reasoning: str = ""
    priority: float = 0.0
    confidence: float = 0.0
    source_event_ids: str = "[]"  # JSON list
    signals: str = "{}"  # JSON dict of signal values
    state_at_issue: str = "{}"
    status: str = "ISSUED"  # ISSUED | CONFIRMED | ACTIONED | EFFECTIVE | PARTIALLY_EFFECTIVE | INEFFECTIVE
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


class User(SQLModel, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    store_id: str = Field(index=True)
    name: str
    role: str = "ASSOCIATE"  # ASSOCIATE | STORE_MANAGER | REGIONAL_ADMIN
    created_at_utc: datetime = Field(default_factory=utcnow)
    updated_at_utc: datetime = Field(default_factory=utcnow)
    sync_status: str = Field(default=SyncStatus.PENDING.value)


# ---------------------------------------------------------------------------
# Engine / session
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal = None


def init_db() -> None:
    """Create tables in SQLite."""
    global _engine, _SessionLocal
    settings = get_settings()
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

    db_url = f"sqlite:///{settings.DB_PATH}"
    _engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(_engine)
    _SessionLocal = Session(bind=_engine)
    logger.info("SQLite database initialized at %s", settings.DB_PATH)


def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    return _SessionLocal  # type: ignore[return-value]


def close_db() -> None:
    global _engine, _SessionLocal
    if _SessionLocal:
        _SessionLocal.close()
    if _engine:
        _engine.dispose()
    logger.info("SQLite database closed")

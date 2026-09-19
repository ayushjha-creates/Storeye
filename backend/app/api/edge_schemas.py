"""Pydantic schemas for the Edge control/live API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class EdgePipelineStatus(BaseModel):
    person_detection: bool
    product_detection: bool
    ocr: bool


class EdgeCameraStatus(BaseModel):
    camera_id: str
    name: str
    kind: str
    running: bool
    connection_ok: bool
    error: Optional[str]
    health: str
    enabled_pipelines: EdgePipelineStatus
    fps: float
    capture_fps: float = 0.0
    inference_fps: float = 0.0
    inference_ms: Optional[float] = None
    last_frame_age_seconds: Optional[float] = None
    frames_captured: int
    frames_processed: int
    frames_dropped: int
    observations_written: int
    last_frame_at: Optional[str]
    last_event_at: Optional[str]
    uptime_seconds: Optional[float]
    started_at: Optional[str]
    # M29: AI pacing + stage timings + hot person-cache stats.
    ai_target_fps: float = 0.0
    stage_profile: dict = {}
    person_cache: Optional[dict] = None
    # M30: periodic shelf-occupancy monitoring status (optional — old
    # deployments / camera configs omit these; the backend keeps working).
    shelf_snapshots_written: int = 0
    shelf_snapshot_interval_seconds: float = 0.0
    last_shelf_scan_at: Optional[str] = None
    # M30 Layer-A: hot shelf-snapshot mirror metrics (optional).
    shelf_snapshot_cache: Optional[dict] = None


class EdgeStatus(BaseModel):
    status: str
    offline: bool
    camera_count: int
    active_cameras: int
    max_cameras: int
    frames_processed: int
    observations_written: int
    last_detection_at: Optional[str]
    models_loaded: list[str]
    now: str
    # M29/M30 Layer-A hot-cache diagnostics (optional — shared runtime only).
    person_cache: Optional[dict] = None
    shelf_snapshot_cache: Optional[dict] = None


class EdgeStartResponse(BaseModel):
    camera_id: str
    started: bool
    running: bool


class EdgeDemoVideoRead(BaseModel):
    """Result of uploading a CCTV clip into the Cameras demo section.

    A real Camera row is created (kind=file) pointing at the saved clip and is
    registered + started in the runtime. The source is the absolute path on the
    edge node; nothing is ever streamed to the cloud.
    """

    camera_id: str
    name: str
    running: bool
    filename: str
    size: int
    source: str
    note: str

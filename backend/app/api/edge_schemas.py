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
    enabled_pipelines: EdgePipelineStatus
    fps: float
    frames_captured: int
    frames_processed: int
    frames_dropped: int
    observations_written: int
    last_frame_at: Optional[str]
    last_event_at: Optional[str]
    uptime_seconds: Optional[float]
    started_at: Optional[str]


class EdgeStatus(BaseModel):
    status: str
    offline: bool
    camera_count: int
    active_cameras: int
    frames_processed: int
    observations_written: int
    last_detection_at: Optional[str]
    models_loaded: list[str]
    now: str


class EdgeStartResponse(BaseModel):
    camera_id: str
    started: bool
    running: bool

"""Pydantic schemas for Camera.

Security note: `config` is where the Edge runtime reads its capture source
(`kind` / `source` / `streamUrl`) from. We validate those keys here so the
UI cannot inject an arbitrary kind or a non-string source that would later
be interpreted unsafely by the Edge capture layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_VALID_CAMERA_TYPES = {"usb", "file", "rtsp"}
_VALID_KINDS = {"usb", "file", "rtsp"}


def _validate_edge_config(v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if v is None:
        return v
    if not isinstance(v, dict):
        raise ValueError("config must be a JSON object")
    kind = v.get("kind")
    if kind is not None and str(kind).lower() not in _VALID_KINDS:
        raise ValueError(
            f"config.kind must be one of {sorted(_VALID_KINDS)}, got {kind!r}"
        )
    if "source" in v and not isinstance(v["source"], str):
        raise ValueError("config.source must be a string")
    if "streamUrl" in v and not isinstance(v["streamUrl"], str):
        raise ValueError("config.streamUrl must be a string")
    for key in ("person_detection", "product_detection", "ocr"):
        if key in v and not isinstance(v[key], bool):
            raise ValueError(f"config.{key} must be a boolean")
    return v


class CameraCreate(BaseModel):
    store_id: UUID
    name: str = Field(..., min_length=1, max_length=150)
    location: Optional[str] = Field(default=None, max_length=200)
    camera_type: str = "usb"
    is_active: bool = True
    config: Optional[dict[str, Any]] = None

    @field_validator("camera_type")
    @classmethod
    def _valid_camera_type(cls, v: str) -> str:
        if v not in _VALID_CAMERA_TYPES:
            raise ValueError(
                f"camera_type must be one of {sorted(_VALID_CAMERA_TYPES)}, got {v!r}"
            )
        return v

    _check_config = field_validator("config")(_validate_edge_config)


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    location: Optional[str] = Field(default=None, max_length=200)
    camera_type: Optional[str] = None
    is_active: Optional[bool] = None
    config: Optional[dict[str, Any]] = None

    @field_validator("camera_type")
    @classmethod
    def _valid_camera_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_CAMERA_TYPES:
            raise ValueError(
                f"camera_type must be one of {sorted(_VALID_CAMERA_TYPES)}, got {v!r}"
            )
        return v

    _check_config = field_validator("config")(_validate_edge_config)


class CameraRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    name: str
    location: Optional[str]
    camera_type: str
    is_active: bool
    config: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class CameraList(BaseModel):
    items: list[CameraRead]
    total: int

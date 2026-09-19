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


def _validate_zone_list(zones: Any) -> None:
    """Validate the M19 camera `zones` mapping (normalized bboxes per zone)."""
    if not isinstance(zones, list):
        raise ValueError("config.zones must be a list")
    for z in zones:
        if not isinstance(z, dict) or not isinstance(z.get("zone_id"), str):
            raise ValueError("each config.zones item needs a string zone_id")
        bbox = z.get("bbox")
        if (
            not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
            or any(not isinstance(v, (int, float)) for v in bbox)
        ):
            raise ValueError("each config.zones item needs a numeric [x1,y1,x2,y2] bbox")


def _validate_shelf_regions(regions: Any) -> None:
    """Validate the M15 manual shelf-region list (shape safety only).

    A region is `{code: str, label?: str, bbox: [x1, y1, x2, y2]}`. Coordinates
    are in the camera's image space (pixels for real feeds; the demo uses a
    0..100 space). There is NO shelf detector — these are operator-configured.
    """
    if not isinstance(regions, list):
        raise ValueError("config.shelf_regions must be a list")
    for r in regions:
        if not isinstance(r, dict):
            raise ValueError("each config.shelf_regions item must be an object")
        code = r.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("each config.shelf_regions item needs a non-empty string code")
        if "label" in r and r["label"] is not None and not isinstance(r["label"], str):
            raise ValueError("config.shelf_regions item label must be a string")
        bbox = r.get("bbox")
        if (
            not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
            or any(not isinstance(v, (int, float)) for v in bbox)
        ):
            raise ValueError(
                "each config.shelf_regions item needs a numeric [x1,y1,x2,y2] bbox"
            )
        x1, y1, x2, y2 = bbox
        if x2 <= x1 or y2 <= y1:
            raise ValueError(
                "config.shelf_regions bbox must have x2 > x1 and y2 > y1"
            )


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

    # ------------------------------------------------------------------
    # M19 journey extensions (all optional, validated for shape safety).
    # ------------------------------------------------------------------
    if "zone_id" in v and not isinstance(v["zone_id"], str):
        raise ValueError("config.zone_id must be a string id")
    if "zones" in v:
        _validate_zone_list(v["zones"])
    if "shelf_regions" in v:
        _validate_shelf_regions(v["shelf_regions"])
    if "fps_cap" in v:
        fps_cap = v["fps_cap"]
        if (
            not isinstance(fps_cap, (int, float))
            or isinstance(fps_cap, bool)
            or fps_cap < 0
        ):
            raise ValueError("config.fps_cap must be a number >= 0")
    if "ai_target_fps" in v:
        ai_fps = v["ai_target_fps"]
        if (
            not isinstance(ai_fps, (int, float))
            or isinstance(ai_fps, bool)
            or ai_fps < 0
        ):
            raise ValueError("config.ai_target_fps must be a number >= 0")
    if "stream_scale" in v:
        scale = v["stream_scale"]
        if (
            not isinstance(scale, (int, float))
            or isinstance(scale, bool)
            or not 0.05 <= scale <= 1.0
        ):
            raise ValueError("config.stream_scale must be a number in [0.05, 1]")
    if "next_cameras" in v:
        if not isinstance(v["next_cameras"], list) or not all(
            isinstance(c, str) for c in v["next_cameras"]
        ):
            raise ValueError("config.next_cameras must be a list of camera id strings")
    if "reid" in v:
        reid = v["reid"]
        if not isinstance(reid, dict):
            raise ValueError("config.reid must be an object")
        if "embedding_refresh_interval_seconds" in reid and (
            not isinstance(reid["embedding_refresh_interval_seconds"], (int, float))
            or reid["embedding_refresh_interval_seconds"] < 0
        ):
            raise ValueError("config.reid.embedding_refresh_interval_seconds must be >= 0")

    # ------------------------------------------------------------------
    # M30 periodic shelf-occupancy knobs (all optional, shape-safe).
    # Validation applies to BOTH the flat config and the nested
    # `config.pipelines` shape the runtime actually reads.
    # ------------------------------------------------------------------
    _m30_targets = [v]
    if isinstance(v.get("pipelines"), dict):
        _m30_targets.append(v["pipelines"])

    for _target in _m30_targets:
        for _key in (
            "product_scan_interval_seconds",
            "shelf_snapshot_interval_seconds",
        ):
            if _key in _target:
                _num = _target[_key]
                if (
                    not isinstance(_num, (int, float))
                    or isinstance(_num, bool)
                    or _num < 0
                ):
                    raise ValueError(f"config.{_key} must be a number >= 0")
        for _key in (
            "shelf_fill_empty_fraction",
            "shelf_fill_low_fraction",
            "shelf_fill_medium_fraction",
            "shelf_occlusion_overlap_fraction",
        ):
            if _key in _target:
                _num = _target[_key]
                if (
                    not isinstance(_num, (int, float))
                    or isinstance(_num, bool)
                    or not 0.0 <= _num <= 1.0
                ):
                    raise ValueError(f"config.{_key} must be a number in [0, 1]")
        _fill_keys = (
            "shelf_fill_empty_fraction",
            "shelf_fill_low_fraction",
            "shelf_fill_medium_fraction",
        )
        if all(_target.get(_k) is not None for _k in _fill_keys):
            _ordered = [float(_target[_k]) for _k in _fill_keys]
            if not (_ordered[0] <= _ordered[1] <= _ordered[2]):
                raise ValueError(
                    "shelf fill fractions must be ordered empty <= low <= medium"
                )
        # M32 open-vocabulary product detection (flat OR nested pipelines).
        if "product_detector" in _target:
            _det = _target["product_detector"]
            if str(_det).lower() not in ("world", "shelf"):
                raise ValueError(
                    "config.product_detector must be 'world' or 'shelf'"
                )
        if "product_prompts" in _target:
            _prompts = _target["product_prompts"]
            if not isinstance(_prompts, list) or not all(
                isinstance(p, str) for p in _prompts
            ):
                raise ValueError("config.product_prompts must be a list of strings")
            if len(_prompts) > 64:
                raise ValueError("config.product_prompts supports at most 64 prompts")
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

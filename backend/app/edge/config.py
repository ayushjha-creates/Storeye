"""Edge AI runtime configuration.

Configuration governs pipeline behaviour per camera (which pipelines are
enabled, inference cadence, OCR cadence, confidence thresholds). Values are
kept conservative for edge hardware and every knob has a sensible default.

This module is deliberately free of heavy AI imports so it can be used by
tests and by the control API without loading any model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CameraKind(str, Enum):
    """Source types the runtime supports (extensible)."""

    VIDEO_FILE = "file"
    WEBCAM = "usb"
    RTSP = "rtsp"  # reserved for future IP-camera support


@dataclass
class PipelineConfig:
    """Per-camera pipeline switches + inference cadence."""

    person_detection: bool = True
    product_detection: bool = True
    ocr: bool = False

    # Inference cadence: process every `inference_interval`-th frame for the
    # detection models (person + product). Occlusion/skips favour latest frame.
    inference_interval: int = 1  # 1 => every frame
    # OCR is expensive: only run when the running frame index hits this stride.
    ocr_interval: int = 30  # 0 disables OCR regardless of `ocr` flag

    # Confidence floor applied after the model's own base threshold.
    confidence_threshold: float = 0.25

    # Frame skipping at the source (read N frames, process 1). Reduces CPU when
    # the stream FPS is higher than the machine can infer.
    frame_skip: int = 0

    # Throttling: at most one PERSON / PRODUCT / TEXT / EXPIRY_METADATA
    # observation per `min_observation_gap_seconds` per camera. Prevents the
    # database being flooded with repetitive per-frame rows.
    min_observation_gap_seconds: float = 2.0

    def validate(self) -> None:
        if self.inference_interval < 1:
            raise ValueError("inference_interval must be >= 1")
        if self.ocr_interval < 0:
            raise ValueError("ocr_interval must be >= 0")
        if self.frame_skip < 0:
            raise ValueError("frame_skip must be >= 0")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in [0, 1]")
        if self.min_observation_gap_seconds < 0:
            raise ValueError("min_observation_gap_seconds must be >= 0")


@dataclass
class CameraConfig:
    """Source config for a single camera in the runtime."""

    camera_id: str
    kind: CameraKind
    # For VIDEO_FILE: an absolute or relative path. For WEBCAM: an integer
    # device index (0-based) or an integer-as-string. For RTSP: a URL (future).
    source: str = "0"
    name: str = "Camera"
    pipelines: PipelineConfig = field(default_factory=PipelineConfig)

    @property
    def device_index(self) -> int | None:
        """Integer device index for webcam sources, else None."""
        if self.kind == CameraKind.WEBCAM:
            try:
                return int(self.source)
            except (TypeError, ValueError):
                return 0
        return None

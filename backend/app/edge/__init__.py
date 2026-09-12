"""Storeye Edge AI Runtime.

Offline-first, on-premises camera AI:
    Camera -> EdgeRuntime -> AI pipelines (person/product/OCR) -> Events
        -> ObservationService -> PostgreSQL.

The runtime never blocks FastAPI, never requires internet, never stores raw
video in PostgreSQL, and never mutates inventory/batches/bills. The heavy AI
models are injectable so tests can use lightweight fakes.
"""

from __future__ import annotations

from .config import CameraConfig, PipelineConfig, CameraKind
from .camera import (
    CameraSource,
    VideoFileSource,
    WebcamSource,
    RTSPSource,
    CameraError,
    EndOfStream,
    create_camera_source,
)
from .frame import CameraFrame
from .events import (
    EdgeEvent,
    EventKind,
    Detection,
    PersonDetection,
    ProductDetection,
    OCRText,
    OCRParsed,
    person_event,
    product_event,
    text_event,
    expiry_event,
)
from .pipeline import EdgePipeline
from .runtime import EdgeRuntime
from .registry import get_runtime, set_runtime
from .workers import CameraWorker
from .models import (
    PersonTrackerModel,
    FakePersonTracker,
    PersonFrameResult,
    ProductDetectorModel,
    FakeProductDetector,
    OCRModel,
    FakeOCR,
)
from .models.registry import ModelRegistry
from .observation_writer import ObservationWriter

__all__ = [
    "CameraConfig",
    "PipelineConfig",
    "CameraKind",
    "CameraSource",
    "VideoFileSource",
    "WebcamSource",
    "RTSPSource",
    "CameraError",
    "EndOfStream",
    "create_camera_source",
    "CameraFrame",
    "EdgeEvent",
    "EventKind",
    "Detection",
    "PersonDetection",
    "ProductDetection",
    "OCRText",
    "OCRParsed",
    "person_event",
    "product_event",
    "text_event",
    "expiry_event",
    "EdgePipeline",
    "EdgeRuntime",
    "get_runtime",
    "set_runtime",
    "CameraWorker",
    "ModelRegistry",
    "PersonTrackerModel",
    "FakePersonTracker",
    "PersonFrameResult",
    "ProductDetectorModel",
    "FakeProductDetector",
    "OCRModel",
    "FakeOCR",
    "ObservationWriter",
]

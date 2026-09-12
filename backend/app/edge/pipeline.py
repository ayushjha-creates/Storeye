"""Edge AI pipeline.

Runs the configured model taps (person, product, OCR) on a single frame and
produces:

  1. a list of structured EdgeEvents (for observation persistence), and
  2. an annotated BGR frame (for the live MJPEG stream).

The pipeline is stateless apart from a per-camera frame counter and the
injected model instances (which own tracker state). It NEVER writes to the
database and NEVER mutates inventory/batches/bills — it only emits events.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple

from .config import CameraConfig, PipelineConfig
from .events import (
    EdgeEvent,
    EventKind,
    PersonDetection,
    ProductDetection,
    text_event,
    expiry_event,
    person_event,
    product_event,
)
from .frame import CameraFrame
from .models.person_detector import PersonTrackerModel, PersonFrameResult
from .models.product_detector import ProductDetectorModel, ProductFrameResult
from .models.ocr import OCRModel, OCRFrameResult

logger = logging.getLogger("storeye.edge.pipeline")


class EdgePipeline:
    """One pipeline instance per camera (owns the camera's model state)."""

    def __init__(
        self,
        *,
        camera_id: str,
        config: PipelineConfig,
        person_model: Optional[PersonTrackerModel] = None,
        product_model: Optional[ProductDetectorModel] = None,
        ocr_model: Optional[OCRModel] = None,
        source_label: Optional[str] = None,
    ) -> None:
        self.camera_id = camera_id
        self.config = config
        self.source_label = source_label
        self._person = person_model
        self._product = product_model
        self._ocr = ocr_model
        self._frame_counter = 0
        self._last_events: List[EdgeEvent] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    @property
    def frame_counter(self) -> int:
        return self._frame_counter

    @property
    def last_events(self) -> List[EdgeEvent]:
        return list(self._last_events)

    def process(self, frame: CameraFrame) -> Tuple[List[EdgeEvent], object | None]:
        """Process one frame -> (events, annotated_bgr_frame | None).

        An annotated frame is only produced when an annotation backend is
        available (e.g. OpenCV; provided by the runtime's streamer).
        """
        self._frame_counter += 1
        events: List[EdgeEvent] = []
        run_inference = (
            (self._frame_counter - 1) % self.config.inference_interval == 0
        )

        if self.config.person_detection and self._person is not None and run_inference:
            events.extend(self._person_tap(frame))
        if self.config.product_detection and self._product is not None and run_inference:
            events.extend(self._product_tap(frame))
        events.extend(self._ocr_tap(frame))

        self._last_events = events
        return events, None

    # ------------------------------------------------------------------
    # Tap implementations (model -> normalized events)
    # ------------------------------------------------------------------
    def _person_tap(self, frame: CameraFrame) -> List[EdgeEvent]:
        results: List[PersonFrameResult] = self._person.track_frame(frame.image)
        out: List[EdgeEvent] = []
        for r in results:
            if r.confidence < self.config.confidence_threshold:
                continue
            out.append(
                person_event(
                    camera_id=frame.camera_id,
                    frame_number=frame.frame_index,
                    timestamp=frame.timestamp,
                    track_id=r.track_id,
                    confidence=r.confidence,
                    bbox_xyxy=r.bbox_xyxy,
                    source=self.source_label,
                )
            )
        return out

    def _product_tap(self, frame: CameraFrame) -> List[EdgeEvent]:
        results: List[ProductFrameResult] = self._product.detect_frame(frame.image)
        out: List[EdgeEvent] = []
        for r in results:
            if r.confidence < self.config.confidence_threshold:
                continue
            out.append(
                product_event(
                    camera_id=frame.camera_id,
                    frame_number=frame.frame_index,
                    timestamp=frame.timestamp,
                    class_name=r.class_name,
                    confidence=r.confidence,
                    bbox_xyxy=r.bbox_xyxy,
                    source=self.source_label,
                )
            )
        return out

    def _ocr_tap(self, frame: CameraFrame) -> List[EdgeEvent]:
        """Experimental, opt-in camera OCR text tap (see `edge/models/ocr.py`).

        Off by default. This tap must NEVER be used as a source of business
        truth: for accurate, reliable batch/expiry/MRP metadata use Smart Batch
        Receiving close-up capture (`app/services/batch_intake/`).
        """
        if not self.config.ocr or self._ocr is None:
            return []
        if self.config.ocr_interval <= 0:
            return []
        if (self._frame_counter - 1) % self.config.ocr_interval != 0:
            return []
        result: OCRFrameResult = self._ocr.ocr_frame(frame.image)
        out: List[EdgeEvent] = []
        # Emit one TEXT event per OCR line.
        for line in result.lines:
            out.append(
                text_event(
                    camera_id=frame.camera_id,
                    frame_number=frame.frame_index,
                    timestamp=frame.timestamp,
                    text=line.text,
                    confidence=line.confidence,
                    bbox_xyxy=line.bbox_xyxy,
                    source=self.source_label,
                )
            )
        # Emit one EXPIRY_METADATA event when parsing produced metadata.
        if result.expiry is not None:
            out.append(
                expiry_event(
                    camera_id=frame.camera_id,
                    frame_number=frame.frame_index,
                    timestamp=frame.timestamp,
                    raw_text="\n".join(line.text for line in result.lines),
                    text_items=[vars(l) for l in result.lines],
                    expiry=result.expiry.__dict__ if result.expiry else None,
                    confidence=result.confidence,
                    status=result.status,
                    source=self.source_label,
                )
            )
        return out

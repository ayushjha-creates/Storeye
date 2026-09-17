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
    track_assoc_event,
    zone_enter_event,
    zone_exit_event,
)
from .frame import CameraFrame
from .models.person_detector import PersonTrackerModel, PersonFrameResult
from .models.product_detector import ProductDetectorModel, ProductFrameResult
from .models.ocr import OCRModel, OCRFrameResult
from ..services.journeys.reid.models import PersonSighting

logger = logging.getLogger("storeye.edge.pipeline")


class EdgePipeline:
    """One pipeline instance per camera (owns the camera's model state).

    M19: the pipeline is also the Re-ID sampling point. It crops + embeds each
    tracked person on a throttle (new track -> embed now; stable track -> reuse
    until `refresh_interval_seconds` elapses), feeds the `PersonSighting` to a
    shared `GlobalIdentityManager`, and enriches person events with the
    anonymous global id. It additionally emits TRACK_ASSOC / ZONE_ENTER /
    ZONE_EXIT journey events that the writer persists to the journeys tables.

    Fail-graceful contract: if Re-ID is disabled or its provider is unusable,
    the pipeline emits plain person events exactly as before — single-camera
    tracking and observations are completely unaffected.
    """

    def __init__(
        self,
        *,
        camera_id: str,
        config: PipelineConfig,
        person_model: Optional[PersonTrackerModel] = None,
        product_model: Optional[ProductDetectorModel] = None,
        ocr_model: Optional[OCRModel] = None,
        source_label: Optional[str] = None,
        reid_manager=None,
        store_id: Optional[str] = None,
        camera_zone_id: Optional[str] = None,
        camera_zones: Optional[list] = None,
    ) -> None:
        self.camera_id = camera_id
        self.config = config
        self.source_label = source_label
        self._person = person_model
        self._product = product_model
        self._ocr = ocr_model
        self._frame_counter = 0
        self._last_events: List[EdgeEvent] = []

        # M19 journey/reid wiring (all optional).
        self.reid_manager = reid_manager
        self.store_id = store_id
        self.camera_zone_id = camera_zone_id
        self.camera_zones = list(camera_zones or [])
        # track_id -> (global_person_id, reid_confidence)
        self._track_meta: dict = {}
        # track_id -> current zone id (or None) for enter/exit detection.
        self._zone_state: dict = {}
        # Sampling bookkeeping: track_id -> last embed timestamp.
        self._last_embed_at: dict = {}

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
        height, width = 0, 0
        if frame.image is not None and getattr(frame.image, "ndim", 0) >= 2:
            height, width = frame.image.shape[:2]

        for r in results:
            if r.confidence < self.config.confidence_threshold:
                continue
            gid, reid_confidence = None, None
            if self.reid_manager is not None and self.reid_manager.reid_available():
                gid, reid_confidence = self._reid_tap(frame, r, width, height, out)
            zone_id = self._zone_tap(frame, r, width, height, gid, out)

            out.append(
                person_event(
                    camera_id=frame.camera_id,
                    frame_number=frame.frame_index,
                    timestamp=frame.timestamp,
                    track_id=r.track_id,
                    confidence=r.confidence,
                    bbox_xyxy=r.bbox_xyxy,
                    source=self.source_label,
                    global_person_id=gid,
                    reid_confidence=reid_confidence,
                    zone_id=zone_id or self.camera_zone_id,
                )
            )
        return out

    # ------------------------------------------------------------------
    # Re-ID + zone taps (M19)
    # ------------------------------------------------------------------
    def _reid_tap(self, frame, r: PersonFrameResult, width: int, height: int, out: List[EdgeEvent]):
        """Sample + associate one person detection to an anonymous global id.

        Returns (global_person_id|None, reid_confidence|None). Appends a
        TRACK_ASSOC event when the track's global assignment changes.
        """
        manager = self.reid_manager
        now = frame.timestamp

        embedding = None
        last_embed = self._last_embed_at.get(r.track_id)
        refresh = manager.config.refresh_interval_seconds
        if last_embed is None or (now - last_embed).total_seconds() >= refresh:
            crop = self._crop(frame.image, r.bbox_xyxy)
            if crop is not None and manager.provider is not None:
                try:
                    embedding = manager.provider.encode(crop)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Re-ID encode failed for camera %s track %s", self.camera_id, r.track_id)
            self._last_embed_at[r.track_id] = now

        sighting = PersonSighting(
            store_id=self.store_id or "",
            camera_id=self.camera_id,
            track_id=r.track_id,
            timestamp=now,
            embedding=embedding,
            foot_point=self._foot_point(r.bbox_xyxy, width, height),
            bbox_xyxy=tuple(float(v) for v in r.bbox_xyxy),
        )

        try:
            match = manager.associate(sighting)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Re-ID association failed for camera %s track %s", self.camera_id, r.track_id)
            return self._track_meta.get(r.track_id, (None, None))

        if match is None:
            return self._track_meta.get(r.track_id, (None, None))

        gid = match.global_person_id
        confidence = match.confidence.value
        previous = self._track_meta.get(r.track_id, (None, None))
        if gid != previous[0]:
            out.append(
                track_assoc_event(
                    camera_id=frame.camera_id,
                    frame_number=frame.frame_index,
                    timestamp=frame.timestamp,
                    track_id=r.track_id,
                    global_person_id=gid,
                    confidence=confidence,
                    source=self.source_label,
                )
            )
        self._track_meta[r.track_id] = (gid, confidence)
        return gid, confidence

    def _zone_tap(self, frame, r: PersonFrameResult, width: int, height: int, gid: Optional[str], out: List[EdgeEvent]):
        """Detect zone enter/exit for a track and emit the matching events."""
        zone = self._zone_at_foot(r.bbox_xyxy, width, height)
        previous = self._zone_state.get(r.track_id)
        if zone != previous:
            if previous is not None and gid is not None:
                out.append(
                    zone_exit_event(
                        camera_id=frame.camera_id,
                        frame_number=frame.frame_index,
                        timestamp=frame.timestamp,
                        track_id=r.track_id,
                        global_person_id=gid,
                        zone_id=previous,
                        confidence=self._track_meta.get(r.track_id, (None, None))[1] or "UNKNOWN",
                        bbox_xyxy=r.bbox_xyxy,
                        source=self.source_label,
                    )
                )
            if zone is not None and gid is not None:
                out.append(
                    zone_enter_event(
                        camera_id=frame.camera_id,
                        frame_number=frame.frame_index,
                        timestamp=frame.timestamp,
                        track_id=r.track_id,
                        global_person_id=gid,
                        zone_id=zone,
                        confidence=self._track_meta.get(r.track_id, (None, None))[1] or "UNKNOWN",
                        bbox_xyxy=r.bbox_xyxy,
                        source=self.source_label,
                    )
                )
            self._zone_state[r.track_id] = zone
        return zone

    def _zone_at_foot(self, bbox_xyxy, width: int, height: int) -> Optional[str]:
        if not self.camera_zones or width <= 0 or height <= 0:
            return None
        x1, y1, x2, y2 = (float(v) for v in bbox_xyxy)
        fx = ((x1 + x2) / 2.0) / width
        fy = y2 / height
        for region in self.camera_zones:
            zbox = region.get("bbox") or []
            if len(zbox) != 4:
                continue
            zx1, zy1, zx2, zy2 = (float(v) for v in zbox)
            if zx1 <= fx <= zx2 and zy1 <= fy <= zy2:
                return region.get("zone_id")
        return None

    @staticmethod
    def _foot_point(bbox_xyxy, width: int, height: int):
        if width <= 0 or height <= 0:
            return None
        x1, _y1, x2, y2 = (float(v) for v in bbox_xyxy)
        return (((x1 + x2) / 2.0) / width, y2 / height)

    @staticmethod
    def _crop(image, bbox_xyxy):
        if image is None:
            return None
        try:
            x1, y1, x2, y2 = (int(round(float(v))) for v in bbox_xyxy)
            h, w = image.shape[:2]
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(x1 + 1, min(x2, w))
            y2 = max(y1 + 1, min(y2, h))
            region = image[y1:y2, x1:x2]
            return region if region.size > 0 else None
        except Exception:  # pragma: no cover - defensive
            return None

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

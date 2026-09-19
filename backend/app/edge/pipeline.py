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
import time
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

import numpy as np

from .config import CameraConfig, PipelineConfig
from .events import (
    EdgeEvent,
    EventKind,
    PersonDetection,
    ProductDetection,
    ShelfSnapshotPayload,
    text_event,
    expiry_event,
    person_event,
    product_event,
    shelf_snapshot_event,
    track_assoc_event,
    zone_enter_event,
    zone_exit_event,
)
from .frame import CameraFrame
from .models.person_detector import PersonTrackerModel, PersonFrameResult
from .models.product_detector import ProductDetectorModel, ProductFrameResult
from .models.ocr import OCRModel, OCRFrameResult
from .person_cache import PersonState, PersonStateManager
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

    M29: the pipeline is a price-aware CASCADE. A local track must be seen for
    ``stable_track_min_frames`` consecutive frames before it is promoted to
    "stable" and ANY expensive downstream work runs (Re-ID association, person
    hot-cache promotion, zone/journey processing). The expensive Re-ID
    EMBEDDING INFERENCE only runs when required — new track, track became
    stable, camera changed, reappearance, or a scheduled refresh; otherwise the
    existing association is reused with a cheap recency touch and the
    ``reid_skipped`` counter advances. Live person events keep flowing on
    every frame so the MJPEG stream stays animated.

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
        person_state: Optional[PersonStateManager] = None,
        store_id: Optional[str] = None,
        camera_zone_id: Optional[str] = None,
        camera_zones: Optional[list] = None,
        shelf_regions: Optional[list] = None,
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
        # M29 Layer A hot cache (shared for the whole store).
        self.person_state = person_state
        self.store_id = store_id
        self.camera_zone_id = camera_zone_id
        self.camera_zones = list(camera_zones or [])
        # M30 manual shelf regions (configured in `camera.config.shelf_regions`,
        # forwarded by the runtime). When no custom regions are defined, provide
        # a default full-view shelf region so fill detection works out of the box.
        self.shelf_regions = list(shelf_regions or [])
        if not self.shelf_regions and self.config.product_detection and self.config.shelf_snapshot_interval_seconds > 0:
            self.shelf_regions = [{"code": "SHELF-1", "label": "Main Shelf", "bbox": [0.0, 0.0, 1.0, 1.0]}]
        # track_id -> (global_person_id, reid_confidence)
        self._track_meta: dict = {}
        # track_id -> current zone id (or None) for enter/exit detection.
        self._zone_state: dict = {}
        # Sampling bookkeeping: track_id -> last embed timestamp.
        self._last_embed_at: dict = {}
        # M29 stable-track filter: consecutive-frame counters + recency.
        self._track_seen_count: dict = {}
        self._track_last_seen_frame: dict = {}
        # Stage timings for this frame (ms), reported via the omni status.
        self.last_stage_timings: dict = {}
        # M30 bookkeeping: most-recent person/product boxes (px / normalized)
        # so a snapshot frame reuses the SAME frame's detections, and the
        # wall-clock timestamps of the last product run / shelf snapshot.
        self._last_person_boxes_px: List[list] = []
        self._last_product_boxes: List[dict] = []
        self._last_product_events: List[EdgeEvent] = []
        self._last_product_at: Optional[datetime] = None
        self._last_snapshot_at: Optional[datetime] = None

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

        M30 cadence model:
          * person tracking  -> frame-stride (``inference_interval``), live loop
          * product YOLO     -> wall-clock ``product_scan_interval_seconds``
            (0 = every processed frame, the legacy behaviour) UNLESS a shelf
            snapshot is due, in which case the same frame's product boxes are
            (re)used for the occupancy math — product YOLO never runs twice on
            one frame, and the live person loop stays cheap on the in-between
            frames.
          * shelf snapshots  -> wall-clock ``shelf_snapshot_interval_seconds``
            (0 = disabled). When due, ONE frame's product boxes are measured
            against each configured shelf ROI and SHELF_SNAPSHOT events are
            emitted. The cadence clock is the frame's wall-clock capture
            timestamp.
        """
        self._frame_counter += 1
        events: List[EdgeEvent] = []
        self.last_stage_timings = {}
        run_inference = (
            (self._frame_counter - 1) % self.config.inference_interval == 0
        )
        now = frame.timestamp

        if self.config.person_detection and self._person is not None and run_inference:
            events.extend(self._person_tap(frame))

        # M30 wall-clock cadence gates (independent of the frame stride).
        product_cadence = self.config.product_scan_interval_seconds
        snapshot_cadence = self.config.shelf_snapshot_interval_seconds
        shelves_enabled = snapshot_cadence > 0 and bool(self.shelf_regions)
        product_due = self._cadence_due("_last_product_at", product_cadence, now)
        snapshot_due = shelves_enabled and self._cadence_due(
            "_last_snapshot_at", snapshot_cadence, now
        )

        run_product = self._product is not None and (
            (self.config.product_detection and product_due) or snapshot_due
        )
        if run_product:
            prod_events = self._product_tap(
                frame, emit=self.config.product_detection and product_due
            )
            events.extend(prod_events)
            if prod_events:
                self._last_product_events = list(prod_events)
        if snapshot_due:
            events.extend(self._shelf_snapshot_tap(frame))
        # OCR keeps its own frame-stride gate; it self-disables on interval<=0.
        events.extend(self._ocr_tap(frame))

        # Maintain display events for video streaming annotations so product
        # bounding boxes stay rock-solid on screen between product scans.
        display_events = list(events)
        if not run_product and self._last_product_events:
            display_events.extend(self._last_product_events)
        self._last_events = display_events
        return events, None

    def _cadence_due(self, attr: str, interval: float, now: datetime) -> bool:
        """Wall-clock cadence gate.

        `interval <= 0` means "every frame" (uncapped — the codebase's 0 =
        uncapped convention), which keeps legacy per-frame behaviour reachable
        while 30s+ cadences are the new default.
        """
        if interval <= 0:
            return True
        last = getattr(self, attr, None)
        if last is None:
            return True
        return (now - last).total_seconds() >= interval

    # ------------------------------------------------------------------
    # Tap implementations (model -> normalized events)
    # ------------------------------------------------------------------
    def _person_tap(self, frame: CameraFrame) -> List[EdgeEvent]:
        t0 = time.perf_counter()
        results: List[PersonFrameResult] = self._person.track_frame(frame.image)
        self.last_stage_timings["person_total_ms"] = (
            (time.perf_counter() - t0) * 1000.0
        )
        out: List[EdgeEvent] = []
        height, width = 0, 0
        if frame.image is not None and getattr(frame.image, "ndim", 0) >= 2:
            height, width = frame.image.shape[:2]

        seen_tracks = set()
        person_boxes: List[list] = []
        for r in results:
            if r.confidence < self.config.confidence_threshold:
                continue
            seen_tracks.add(r.track_id)
            person_boxes.append(list(r.bbox_xyxy))

            # --- M29 stable-track filter ------------------------------
            count = self._track_seen_count.get(r.track_id, 0) + 1
            self._track_seen_count[r.track_id] = count
            self._track_last_seen_frame[r.track_id] = self._frame_counter
            stable = count >= self.config.stable_track_min_frames

            gid, reid_confidence = None, None
            if (
                stable
                and self.reid_manager is not None
                and self.reid_manager.reid_available()
            ):
                gid, reid_confidence = self._reid_tap(
                    frame, r, width, height, out, cache_first=count > 1
                )
                # Promote to the hot state cache (Layer A) after association.
                if gid and self.person_state is not None:
                    self.person_state.upsert(
                        store_id=self.store_id or "",
                        global_person_id=gid,
                        camera_id=frame.camera_id,
                        track_id=r.track_id,
                        timestamp=frame.timestamp,
                        zone_id=self._zone_at_foot(
                            r.bbox_xyxy, width, height
                        ),
                        confidence=reid_confidence or "UNKNOWN",
                        reid_used=count == 1,
                    )

            zone_id = None
            if stable and gid is not None:
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
                    bbox_norm=(
                        self._normalize_box(r.bbox_xyxy, width, height)
                        if width > 0 and height > 0
                        else None
                    ),
                )
            )

        self._forget_stale_tracks(seen_tracks)
        # M30: keep the most-recent person boxes for the occlusion check at
        # snapshot time (the snapshot frame may not be a person-inference frame).
        self._last_person_boxes_px = person_boxes
        return out

    def _forget_stale_tracks(self, seen: Iterable[int]) -> None:
        """Decay counters for tracks that vanished this frame; forget entries
        that have been gone long enough. ByteTrack IDs are small ints, but
        under re-creation they can churn indefinitely — bound the bookkeeping."""
        seen = set(seen)
        for tid in list(self._track_seen_count):
            if tid not in seen:
                self._track_seen_count[tid] -= 1
                if self._track_seen_count[tid] <= 0:
                    self._track_seen_count.pop(tid, None)
        # Forget association/zone/embed bookkeeping for tracks gone ~10s
        # (300 frames at the default inference cadence).
        oldest = self._frame_counter - 300
        for tid in list(self._track_last_seen_frame):
            if tid in seen:
                continue
            if self._track_last_seen_frame[tid] < oldest:
                self._track_meta.pop(tid, None)
                self._zone_state.pop(tid, None)
                self._last_embed_at.pop(tid, None)
                self._track_last_seen_frame.pop(tid, None)

    # ------------------------------------------------------------------
    # Re-ID + zone taps (M19 / M29)
    # ------------------------------------------------------------------
    def _reid_tap(
        self,
        frame,
        r: PersonFrameResult,
        width: int,
        height: int,
        out: List[EdgeEvent],
        cache_first: bool = True,
    ):
        """Associate one person detection to an anonymous global id.

        M29: selective Re-ID. On the hot path we consult the Layer A cache:
        if this local (camera, track) is already associated AND a refresh is
        not due, we reuse the cached id with a cheap recency touch (no
        embedding inference) — that is a ``reid_skipped`` frame. The expensive
        embedding encode + association only runs when the track is new, a
        refresh cadence elapsed (tracks stay appearance-fresh for cross-camera
        Re-ID), or the cache disagreed.

        Returns (global_person_id|None, reid_confidence|None).
        """
        manager = self.reid_manager
        now = frame.timestamp
        t_reid = time.perf_counter()
        previous = self._track_meta.get(r.track_id, (None, None))
        refresh = manager.config.refresh_interval_seconds

        # Hot path: cache hit + not refresh-due -> reuse, count a skip.
        cached = None
        if cache_first and previous[0] is not None:
            if self.person_state is not None:
                cached = self.person_state.resolve_track(
                    self.store_id or "", frame.camera_id, r.track_id
                )
            last_embed = self._last_embed_at.get(r.track_id)
            due = (
                last_embed is None
                or (now - last_embed).total_seconds() >= refresh
            )
            # Cheap recency touch keeps the global identity manager's gap
            # logic correct without a re-encode. Its result is still honored —
            # if the manager re-assigned this track (e.g. after a prune), we
            # follow the new global id instead of a phantom cached one.
            if not due:
                recency = None
                try:
                    recency = manager.associate(
                        PersonSighting(
                            store_id=self.store_id or "",
                            camera_id=self.camera_id,
                            track_id=r.track_id,
                            timestamp=now,
                            embedding=None,
                            foot_point=self._foot_point(r.bbox_xyxy, width, height),
                            bbox_xyxy=tuple(float(v) for v in r.bbox_xyxy),
                        )
                    )
                except Exception:  # pragma: no cover - defensive
                    logger.exception(
                        "Re-ID recency touch failed for camera %s track %s",
                        self.camera_id,
                        r.track_id,
                    )
                if self.person_state is not None:
                    self.person_state.count_reid_skip()
                self.last_stage_timings["reid_ms"] = (
                    (time.perf_counter() - t_reid) * 1000.0
                )
                if recency is not None and recency.global_person_id != previous[0]:
                    gid = recency.global_person_id
                    confidence = recency.confidence.value
                    self._track_meta[r.track_id] = (gid, confidence)
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
                    return gid, confidence
                return previous[0], previous[1]

        embedding = None
        last_embed = self._last_embed_at.get(r.track_id)
        if last_embed is None or (now - last_embed).total_seconds() >= refresh:
            crop = self._crop(frame.image, r.bbox_xyxy)
            if crop is not None and manager.provider is not None:
                try:
                    embedding = manager.provider.encode(crop)
                except Exception:  # pragma: no cover - defensive
                    logger.exception(
                        "Re-ID encode failed for camera %s track %s",
                        self.camera_id,
                        r.track_id,
                    )
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
            logger.exception(
                "Re-ID association failed for camera %s track %s",
                self.camera_id,
                r.track_id,
            )
            self.last_stage_timings["reid_ms"] = (
                (time.perf_counter() - t_reid) * 1000.0
            )
            return previous[0], previous[1]

        if self.person_state is not None:
            self.person_state.count_reid_invocation()

        if match is None:
            self.last_stage_timings["reid_ms"] = (
                (time.perf_counter() - t_reid) * 1000.0
            )
            return previous[0], previous[1]

        gid = match.global_person_id
        confidence = match.confidence.value
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
        self.last_stage_timings["reid_ms"] = (
            (time.perf_counter() - t_reid) * 1000.0
        )
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

    def _product_tap(self, frame: CameraFrame, emit: bool = True) -> List[EdgeEvent]:
        t0 = time.perf_counter()
        results: List[ProductFrameResult] = self._product.detect_frame(frame.image)
        out: List[EdgeEvent] = []
        height, width = 0, 0
        if frame.image is not None and getattr(frame.image, "ndim", 0) >= 2:
            height, width = frame.image.shape[:2]
        kept: List[dict] = []
        for r in results:
            if r.confidence < self.config.confidence_threshold:
                continue
            # M30: stash this frame's product boxes (normalized) for the shelf
            # occupancy snapshot. If the product observation cadence is NOT due
            # but a snapshot IS, these same boxes are reused — product YOLO
            # never runs twice on one frame.
            norm = self._normalize_box(r.bbox_xyxy, width, height)
            kept.append(
                {
                    "bbox": norm,
                    "class_name": r.class_name,
                    "confidence": r.confidence,
                }
            )
            if not emit:
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
                    bbox_norm=norm,
                )
            )
        self._last_product_boxes = kept
        # Wall-clock cadence bookkeeping (datetime-typed for _cadence_due).
        if self.config.product_scan_interval_seconds <= 0:
            self._last_product_at = None
        elif emit:
            self._last_product_at = frame.timestamp
        self.last_stage_timings["product_ms"] = (
            (time.perf_counter() - t0) * 1000.0
        )
        return out

    # ------------------------------------------------------------------
    # M30 periodic shelf-occupancy snapshots
    # ------------------------------------------------------------------
    def _shelf_snapshot_tap(self, frame: CameraFrame) -> List[EdgeEvent]:
        """Measure every configured shelf ROI against THIS frame's detections.

        Product boxes come from the product tap that ran on the same frame (or
        the cached run immediately before); person boxes (also current) gate
        occlusion. Emits one ShelfSnapshotPayload per region. Pure geometry —
        no DB writes, no business truth.
        """
        t0 = time.perf_counter()
        out: List[EdgeEvent] = []
        height, width = 0, 0
        if frame.image is not None and getattr(frame.image, "ndim", 0) >= 2:
            height, width = frame.image.shape[:2]
        if width <= 0 or height <= 0:
            return out

        person_boxes = [list(b) for b in self._last_person_boxes_px]
        for region in self.shelf_regions:
            code = region.get("code")
            raw_bbox = region.get("bbox") or []
            if not code or len(raw_bbox) != 4:
                continue
            rx1, ry1, rx2, ry2 = (float(v) for v in raw_bbox)
            # Auto-scale normalized 0..1 bounding boxes to frame pixel dimensions
            if rx2 <= 1.0 and ry2 <= 1.0 and (rx2 > 0 or ry2 > 0):
                rx1, ry1, rx2, ry2 = rx1 * width, ry1 * height, rx2 * width, ry2 * height
            rx1, ry1, rx2, ry2 = self._clip_box(rx1, ry1, rx2, ry2, width, height)
            if rx2 <= rx1 or ry2 <= ry1:
                continue
            region_norm = self._normalize_box(
                [rx1, ry1, rx2, ry2], width, height
            )

            occluded, overlap = self._region_overlap(
                rx1, ry1, rx2, ry2, person_boxes, width, height,
                self.config.shelf_occlusion_overlap_fraction,
            )
            fill = self._region_fill(rx1, ry1, rx2, ry2, width, height)
            status = self._classify_fill(fill)
            products = [
                b
                for b in self._last_product_boxes
                if self._box_in_region(b["bbox"], region_norm)
            ]
            confs = [float(b["confidence"]) for b in products]
            confidence = (
                round(sum(confs) / len(confs), 4) if confs else None
            )
            note = None
            if occluded:
                note = (
                    f"Person blocking shelf {code} "
                    f"({int(round(overlap * 100))}% of the region)"
                )
            out.append(
                shelf_snapshot_event(
                    camera_id=frame.camera_id,
                    frame_number=frame.frame_index,
                    timestamp=frame.timestamp,
                    payload=ShelfSnapshotPayload(
                        shelf_code=code,
                        shelf_label=region.get("label"),
                        region_bbox=region_norm,
                        fill_percentage=round(fill * 100.0, 1),
                        status=status,
                        product_count=len(products),
                        occluded=occluded,
                        occlusion_note=note,
                        confidence=confidence,
                    ),
                    source=self.source_label,
                )
            )
        self._last_snapshot_at = frame.timestamp
        self.last_stage_timings["shelf_ms"] = (
            (time.perf_counter() - t0) * 1000.0
        )
        return out

    def _classify_fill(self, fill: float) -> str:
        """Map a 0..1 region-coverage fraction to a discrete snapshot state.

        Uses the pipeline thresholds (default EMPTY <10 / LOW <=50 (half or less)
        / MEDIUM <70 / FULL >=70). Deliberately separate from the read-time 24h
        ShelfIntelligence labels.
        """
        f = self.config
        if fill < f.shelf_fill_empty_fraction:
            return "EMPTY"
        if fill <= f.shelf_fill_low_fraction:
            return "LOW"
        if fill < f.shelf_fill_medium_fraction:
            return "MEDIUM"
        return "FULL"

    def _region_fill(
        self, rx1: float, ry1: float, rx2: float, ry2: float,
        width: int, height: int,
    ) -> float:
        """Product-box coverage of a region via a coarse grid union mask.

        Pure geometric estimate of visible products; never a business count.
        """
        boxes: List[list] = []
        for det in self._last_product_boxes:
            b = det["bbox"]
            if len(b) != 4:
                continue
            x1, y1, x2, y2 = (float(v) for v in b)
            x1, y1, x2, y2 = self._denormalize_box(x1, y1, x2, y2, width, height)
            x1, y1, x2, y2 = self._clip_box(x1, y1, x2, y2, width, height)
            boxes.append([x1, y1, x2, y2])
        return self._coverage(rx1, ry1, rx2, ry2, boxes)

    @staticmethod
    def _coverage(
        rx1: float, ry1: float, rx2: float, ry2: float, boxes: List[list]
    ) -> float:
        grid_w, grid_h = 100, 60
        mask = np.zeros((grid_h, grid_w), dtype=bool)
        rx2 = max(rx2, rx1 + 1e-6)
        ry2 = max(ry2, ry1 + 1e-6)
        for (x1, y1, x2, y2) in boxes:
            ix1, iy1 = max(x1, rx1), max(y1, ry1)
            ix2, iy2 = min(x2, rx2), min(y2, ry2)
            if ix2 <= ix1 or iy2 <= iy1:
                continue
            gx1 = int((ix1 - rx1) / (rx2 - rx1) * grid_w)
            gx2 = int(np.ceil((ix2 - rx1) / (rx2 - rx1) * grid_w))
            gy1 = int((iy1 - ry1) / (ry2 - ry1) * grid_h)
            gy2 = int(np.ceil((iy2 - ry1) / (ry2 - ry1) * grid_h))
            gx1 = max(0, min(gx1, grid_w - 1))
            gy1 = max(0, min(gy1, grid_h - 1))
            gx2 = max(gx1 + 1, min(gx2, grid_w))
            gy2 = max(gy1 + 1, min(gy2, grid_h))
            mask[gy1:gy2, gx1:gx2] = True
        return float(mask.sum() / mask.size)

    @staticmethod
    def _region_overlap(
        rx1: float, ry1: float, rx2: float, ry2: float,
        person_boxes_px: List[list], width: int, height: int, threshold: float,
    ) -> Tuple[bool, float]:
        """Largest person-box overlap (inter/region) and occlusion boolean."""
        if threshold <= 0:
            return False, 0.0
        rarea = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
        if rarea <= 0:
            return False, 0.0
        best = 0.0
        for box in person_boxes_px:
            if len(box) != 4:
                continue
            x1, y1, x2, y2 = (float(v) for v in box)
            ix1, iy1 = max(x1, rx1), max(y1, ry1)
            ix2, iy2 = min(x2, rx2), min(y2, ry2)
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            best = max(best, inter / rarea)
        return best >= threshold, best

    @staticmethod
    def _box_in_region(box, region_norm) -> bool:
        if len(box) != 4 or len(region_norm) != 4:
            return False
        bx1, by1, bx2, by2 = (float(v) for v in box)
        rx1, ry1, rx2, ry2 = (float(v) for v in region_norm)
        return not (bx2 <= rx1 or bx1 >= rx2 or by2 <= ry1 or by1 >= ry2)

    @staticmethod
    def _clip_box(x1, y1, x2, y2, width: int, height: int):
        return (
            max(0.0, min(x1, float(width))),
            max(0.0, min(y1, float(height))),
            max(0.0, min(x2, float(width))),
            max(0.0, min(y2, float(height))),
        )

    @staticmethod
    def _normalize_box(bbox, width: int, height: int) -> list:
        x1, y1, x2, y2 = (float(v) for v in bbox)
        if width <= 0 or height <= 0:
            return [0.0, 0.0, 0.0, 0.0]
        return [
            max(0.0, min(x1 / width, 1.0)),
            max(0.0, min(y1 / height, 1.0)),
            max(0.0, min(x2 / width, 1.0)),
            max(0.0, min(y2 / height, 1.0)),
        ]

    @staticmethod
    def _denormalize_box(x1, y1, x2, y2, width: int, height: int) -> list:
        if width <= 0 or height <= 0:
            return [0.0, 0.0, 0.0, 0.0]
        return [x1 * width, y1 * height, x2 * width, y2 * height]

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
        t0 = time.perf_counter()
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
        self.last_stage_timings["ocr_ms"] = (time.perf_counter() - t0) * 1000.0
        return out
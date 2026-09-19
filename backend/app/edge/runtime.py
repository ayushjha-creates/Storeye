"""EdgeRuntime — orchestrates zero or more CameraWorkers.

The runtime is a thin controller:

    EdgeRuntime
        ├── CameraWorker A (capture thread + inference thread + pipeline)
        ├── CameraWorker B
        └── ...

It owns the lifecycle (start/stop/status/shutdown), the shared ModelRegistry,
and per-camera state. It does NOT run an uncontrolled loop inside a request —
each camera runs on its own background threads. FastAPI stays responsive.

Model injection: the runtime accepts a ModelRegistry (or fakes) so tests never
load real models. Production uses the real registry with local weights.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from .config import CameraConfig, PipelineConfig
from .models.registry import ModelRegistry
from .pipeline import EdgePipeline
from .workers import CameraWorker

logger = logging.getLogger("storeye.edge.runtime")


class CameraCapacityError(RuntimeError):
    """Raised when starting a camera would exceed the configured capacity."""


class EdgeRuntime:
    """Thread-safe orchestrator of camera workers."""

    def __init__(
        self,
        registry: Optional[ModelRegistry] = None,
        *,
        reid_enabled: Optional[bool] = None,
        max_cameras: Optional[int] = None,
        person_cache_ttl_seconds: Optional[float] = None,
        person_cache_max_entries: Optional[int] = None,
        person_stable_track_min_frames: Optional[int] = None,
        shelf_cache_ttl_seconds: Optional[float] = None,
        shelf_cache_max_entries: Optional[int] = None,
        shelf_cache_per_region_history: Optional[int] = None,
    ) -> None:
        """`reid_enabled` overrides the global setting (used by tests to keep
        the shared manager from instantiating heavy embedding providers).
        `max_cameras` overrides EDGE_MAX_CAMERAS (tests / capacity tuning).
        M29: `person_cache_ttl_seconds / person_cache_max_entries /
        person_stable_track_min_frames` default from Settings but can be
        overridden by tests / embedding-runner wiring.
        M30: `shelf_cache_*` behave the same for the shelf-snapshot mirror."""
        self._registry = registry or ModelRegistry()
        self._reid_override = reid_enabled
        self._max_cameras = max_cameras
        self._person_cache_ttl = person_cache_ttl_seconds
        self._person_cache_max = person_cache_max_entries
        self._stable_min_frames = person_stable_track_min_frames
        self._shelf_cache_ttl = shelf_cache_ttl_seconds
        self._shelf_cache_max = shelf_cache_max_entries
        self._shelf_cache_history = shelf_cache_per_region_history
        # Allow tests to override model loading by monkeypatching these hooks.
        self._workers: Dict[str, CameraWorker] = {}
        self._lock = threading.Lock()
        self._store_id: Optional[str] = None
        # M19: one shared Re-ID identity manager per runtime (all cameras in the
        # store share it so cross-camera association works).
        self._reid = None
        # M29: one shared Layer-A hot cache per runtime (store lives here only).
        self._person_state = None
        # M30: one shared shelf-snapshot hot-mirror per runtime.
        self._shelf_snapshot_cache = None

    # -- configuration ----------------------------------------------------
    def set_store(self, store_id: Optional[str]) -> None:
        self._store_id = store_id

    @property
    def store_id(self) -> Optional[str]:
        return self._store_id

    def max_cameras(self) -> int:
        """Configured concurrent-camera capacity (0 => unlimited)."""
        if self._max_cameras is not None:
            return int(self._max_cameras)
        from ..core.config import get_settings

        try:
            return int(get_settings().EDGE_MAX_CAMERAS)
        except Exception:  # pragma: no cover - defensive
            return 8

    # -- Re-ID (M19) ------------------------------------------------------
    def reid_enabled(self) -> bool:
        if self._reid_override is not None:
            return bool(self._reid_override)
        from ..core.config import get_settings

        try:
            return bool(get_settings().REID_ENABLED)
        except Exception:  # pragma: no cover - defensive
            return False

    def _reid_manager(self):
        """Lazily build the shared GlobalIdentityManager (store-scoped)."""
        if self._reid is None:
            from ..core.config import get_settings
            from ..services.journeys import GlobalIdentityManager, ReIDConfig
            from ..services.journeys.reid.providers import build_reid_provider

            settings = get_settings()
            config = ReIDConfig.from_settings(settings)
            provider = None
            if config.enabled and config.provider:
                try:
                    provider = build_reid_provider(config.provider)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Re-ID provider init failed; falling back to disabled")
            self._reid = GlobalIdentityManager(
                config=config,
                provider=provider,
                store_id=self._store_id,
            )
        return self._reid

    def get_reid_manager(self):
        """Public accessor used by status/tests. Never creates when disabled."""
        if not self.reid_enabled():
            return None
        return self._reid_manager()

    # -- M29 Layer-A hot cache -------------------------------------------
    def _person_state_manager(self):
        """Lazily build the shared store-scoped hot cache (created ONCE per
        runtime — never per frame or per camera)."""
        if self._person_state is None:
            from ..core.config import get_settings
            from .person_cache import PersonStateManager

            settings = get_settings()
            ttl = (
                self._person_cache_ttl
                if self._person_cache_ttl is not None
                else float(getattr(settings, "PERSON_CACHE_TTL_SECONDS", 86400))
            )
            cap = (
                self._person_cache_max
                if self._person_cache_max is not None
                else int(getattr(settings, "PERSON_CACHE_MAX_ENTRIES", 2048))
            )
            self._person_state = PersonStateManager(
                store_id=self._store_id,
                ttl_seconds=ttl,
                max_entries=cap,
            )
        return self._person_state

    def get_person_state(self):
        """Public accessor for the Layer-A cache (tests/status)."""
        return self._person_state_manager()

    # -- M30 shelf-snapshot hot mirror -----------------------------------
    def _shelf_snapshot_cache_manager(self):
        """Lazily build the shared store-scoped shelf-snapshot mirror (created
        ONCE per runtime — never per frame or per camera)."""
        if self._shelf_snapshot_cache is None:
            from ..core.config import get_settings
            from .shelf_snapshot_cache import ShelfSnapshotCache

            settings = get_settings()
            ttl = (
                self._shelf_cache_ttl
                if self._shelf_cache_ttl is not None
                else float(getattr(settings, "SHELF_SNAPSHOT_CACHE_TTL_SECONDS", 86400))
            )
            cap = (
                self._shelf_cache_max
                if self._shelf_cache_max is not None
                else int(getattr(settings, "SHELF_SNAPSHOT_CACHE_MAX_ENTRIES", 4096))
            )
            history = (
                self._shelf_cache_history
                if self._shelf_cache_history is not None
                else int(getattr(settings, "SHELF_SNAPSHOT_CACHE_PER_REGION_HISTORY", 24))
            )
            self._shelf_snapshot_cache = ShelfSnapshotCache(
                store_id=self._store_id,
                ttl_seconds=ttl,
                max_entries=cap,
                per_region_history=history,
            )
        return self._shelf_snapshot_cache

    def get_shelf_snapshot_cache(self):
        """Public accessor for the M30 shelf-snapshot mirror (tests/API)."""
        return self._shelf_snapshot_cache_manager()

    def stable_min_frames(self) -> int:
        if self._stable_min_frames is not None:
            return int(self._stable_min_frames)
        from ..core.config import get_settings

        try:
            return int(get_settings().PERSON_STABLE_TRACK_MIN_FRAMES)
        except Exception:  # pragma: no cover - defensive
            return 1

    # -- model hooks (overridable in tests) -------------------------------
    def _person_tracker(self):
        return self._registry.new_person_tracker()

    def _product_detector(self):
        return self._registry.get_product_detector()

    def _new_product_detector(self, pipelines):
        """Build this camera's product detector (open-vocab or legacy)."""
        return self._registry.new_product_detector(
            detector=getattr(pipelines, "product_detector", "world"),
            prompts=getattr(pipelines, "product_prompts", None),
            conf=pipelines.confidence_threshold,
        )

    def _ocr_model(self):
        return self._registry.get_ocr()

    # -- lifecycle --------------------------------------------------------
    def add_camera(self, config: CameraConfig) -> CameraWorker:
        """Register a camera (not started until .start_camera())."""
        with self._lock:
            if config.camera_id in self._workers:
                return self._workers[config.camera_id]
            reid_manager = (
                self._reid_manager() if self.reid_enabled() else None
            )
            if reid_manager is not None:
                reid_manager.register_camera(config.camera_id, config.next_cameras)
            # OCR is opt-in and its PaddleOCR weights may be unavailable on a
            # given edge machine. Never let a missing OCR model stop the camera:
            # disable the OCR tap and keep person/product running.
            ocr_model = None
            if config.pipelines.ocr:
                try:
                    ocr_model = self._ocr_model()
                except Exception:
                    logger.exception(
                        "OCR model unavailable; camera %s continues without OCR",
                        config.camera_id,
                    )
                    # Reflect reality in status: OCR is not actually running.
                    config.pipelines.ocr = False
            # M29 stable-track floor from global settings (a per-camera value
            # >1 set by an operator wins; the default 1 means "follow global").
            if config.pipelines.person_detection:
                config.pipelines.stable_track_min_frames = (
                    self.stable_min_frames()
                    if config.pipelines.stable_track_min_frames <= 1
                    else config.pipelines.stable_track_min_frames
                )
            # Product detector: open-vocabulary (YOLO-World) by default. Its
            # weights or the CLIP text encoder may be unavailable on a given
            # machine — never let that stop the camera; disable the product tap.
            product_model = None
            if config.pipelines.product_detection:
                try:
                    product_model = self._new_product_detector(config.pipelines)
                except Exception:
                    logger.exception(
                        "Product detector unavailable; camera %s continues "
                        "without product detection",
                        config.camera_id,
                    )
                    config.pipelines.product_detection = False
            pipeline = EdgePipeline(
                camera_id=config.camera_id,
                config=config.pipelines,
                person_model=self._person_tracker() if config.pipelines.person_detection else None,
                product_model=product_model,
                ocr_model=ocr_model,
                source_label=f"edge:{config.kind.value}:{config.source}",
                reid_manager=reid_manager,
                person_state=(
                    self._person_state_manager()
                    if config.pipelines.person_detection
                    else None
                ),
                store_id=self._store_id,
                camera_zone_id=config.zone_id,
                camera_zones=config.camera_zones,
                shelf_regions=config.shelf_regions,
            )
            worker = CameraWorker(
                config,
                pipeline=pipeline,
                store_id=self._store_id,
                fps_cap=config.fps_cap,
                ai_target_fps=config.ai_target_fps,
                stream_scale=config.stream_scale,
                shelf_snapshot_cache=(
                    self._shelf_snapshot_cache_manager()
                    if config.pipelines.product_detection
                    or config.pipelines.shelf_snapshot_interval_seconds > 0
                    else None
                ),
            )
            self._workers[config.camera_id] = worker
            logger.info("Registered camera %s", config.camera_id)
            return worker

    def start_camera(self, camera_id: str) -> CameraWorker:
        worker = self._get(camera_id)
        if not worker.running:
            cap = self.max_cameras()
            running_others = sum(
                1 for cid, w in self.workers().items() if w.running and cid != camera_id
            )
            if cap > 0 and running_others >= cap:
                raise CameraCapacityError(
                    f"Camera capacity reached ({cap} running). "
                    "Stop a camera before starting another."
                )
        worker.start()
        return worker

    def stop_camera(self, camera_id: str, timeout: float = 5.0) -> None:
        worker = self._get(camera_id)
        worker.stop(timeout=timeout)

    def reconcile(self, active_camera_ids: Iterable[str]) -> list:
        """Runtime↔DB supervisor: stop + remove workers whose DB camera is no
        longer active (inactive or deleted). Returns the removed camera ids.

        Cameras that are active in the DB but merely stopped stay registered so
        they can be restarted cheaply and keep their cross-camera graph edges.
        """
        active = {str(c) for c in active_camera_ids}
        removed = []
        for cid in list(self.workers().keys()):
            if cid not in active:
                self.remove_camera(cid)
                removed.append(cid)
        if removed:
            logger.info("Supervisor removed stale camera workers: %s", removed)
        return removed

    def remove_camera(self, camera_id: str) -> None:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker is not None and worker.running:
            worker.stop()

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            cameras = list(self._workers.keys())
        for cid in cameras:
            try:
                self.stop_camera(cid, timeout=timeout)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Error stopping camera %s", cid)
        with self._lock:
            self._workers.clear()

    # -- status -----------------------------------------------------------
    def _get(self, camera_id: str) -> CameraWorker:
        worker = self._workers.get(camera_id)
        if worker is None:
            raise KeyError(f"Camera not registered: {camera_id}")
        return worker

    def has_camera(self, camera_id: str) -> bool:
        return camera_id in self._workers

    def workers(self) -> Dict[str, CameraWorker]:
        """Return a snapshot dict of camera_id -> worker."""
        with self._lock:
            return dict(self._workers)

    def get_worker(self, camera_id: str) -> Optional[CameraWorker]:
        return self._workers.get(camera_id)

    def camera_status(self, camera_id: str) -> dict:
        return self._get(camera_id).status()

    def cameras(self) -> list:
        return [w.status() for w in self._workers.values()]

    def active_cameras(self) -> int:
        return sum(1 for w in self._workers.values() if w.running)

    def status(self) -> dict:
        now = datetime.now(timezone.utc)
        last = None
        for w in self._workers.values():
            if w.last_event_at and (last is None or w.last_event_at > last):
                last = w.last_event_at
        total_processed = sum(w.frames_processed for w in self._workers.values())
        total_written = sum(w.observations_written for w in self._workers.values())
        out = {
            "status": "running" if self.active_cameras() > 0 else "stopped",
            "offline": True,  # Storeye is offline-first by design
            "camera_count": len(self._workers),
            "active_cameras": self.active_cameras(),
            "max_cameras": self.max_cameras(),
            "frames_processed": total_processed,
            "observations_written": total_written,
            "last_detection_at": last.isoformat() if last else None,
            "models_loaded": self._registry.loaded_model_names(),
            "now": now.isoformat(),
        }
        if self._person_state is not None:
            out["person_cache"] = self._person_state.public_stats()
        if self._shelf_snapshot_cache is not None:
            out["shelf_snapshot_cache"] = self._shelf_snapshot_cache.public_stats()
        return out

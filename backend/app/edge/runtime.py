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
from typing import Dict, Optional

from .config import CameraConfig, PipelineConfig
from .models.registry import ModelRegistry
from .pipeline import EdgePipeline
from .workers import CameraWorker

logger = logging.getLogger("storeye.edge.runtime")


class EdgeRuntime:
    """Thread-safe orchestrator of camera workers."""

    def __init__(
        self,
        registry: Optional[ModelRegistry] = None,
        *,
        reid_enabled: Optional[bool] = None,
    ) -> None:
        """`reid_enabled` overrides the global setting (used by tests to keep
        the shared manager from instantiating heavy embedding providers)."""
        self._registry = registry or ModelRegistry()
        self._reid_override = reid_enabled
        # Allow tests to override model loading by monkeypatching these hooks.
        self._workers: Dict[str, CameraWorker] = {}
        self._lock = threading.Lock()
        self._store_id: Optional[str] = None
        # M19: one shared Re-ID identity manager per runtime (all cameras in the
        # store share it so cross-camera association works).
        self._reid = None

    # -- configuration ----------------------------------------------------
    def set_store(self, store_id: Optional[str]) -> None:
        self._store_id = store_id

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

    # -- model hooks (overridable in tests) -------------------------------
    def _person_tracker(self):
        return self._registry.new_person_tracker()

    def _product_detector(self):
        return self._registry.get_product_detector()

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
            pipeline = EdgePipeline(
                camera_id=config.camera_id,
                config=config.pipelines,
                person_model=self._person_tracker() if config.pipelines.person_detection else None,
                product_model=self._product_detector() if config.pipelines.product_detection else None,
                ocr_model=self._ocr_model() if config.pipelines.ocr else None,
                source_label=f"edge:{config.kind.value}:{config.source}",
                reid_manager=reid_manager,
                store_id=self._store_id,
                camera_zone_id=config.zone_id,
                camera_zones=config.camera_zones,
            )
            worker = CameraWorker(
                config,
                pipeline=pipeline,
                store_id=self._store_id,
                fps_cap=0.0,
            )
            self._workers[config.camera_id] = worker
            logger.info("Registered camera %s", config.camera_id)
            return worker

    def start_camera(self, camera_id: str) -> CameraWorker:
        worker = self._get(camera_id)
        worker.start()
        return worker

    def stop_camera(self, camera_id: str, timeout: float = 5.0) -> None:
        worker = self._get(camera_id)
        worker.stop(timeout=timeout)

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
        return {
            "status": "running" if self.active_cameras() > 0 else "stopped",
            "offline": True,  # Storeye is offline-first by design
            "camera_count": len(self._workers),
            "active_cameras": self.active_cameras(),
            "frames_processed": total_processed,
            "observations_written": total_written,
            "last_detection_at": last.isoformat() if last else None,
            "models_loaded": self._registry.loaded_model_names(),
            "now": now.isoformat(),
        }

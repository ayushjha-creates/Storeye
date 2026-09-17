"""Edge AI Runtime control + live stream API.

These endpoints let the frontend start/stop cameras, inspect runtime/status and
watch the local annotated MJPEG stream. Everything runs on the local Edge node;
no internet or cloud is required.

Security: the stream and control endpoints are LOCAL services (bound to the
store network / localhost). No public exposure, no arbitrary command execution —
we only ever start/stop cameras that already exist in the local PostgreSQL
`cameras` table.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..edge import (
    CameraConfig,
    CameraKind,
    PipelineConfig,
    EventKind,
    get_runtime,
    EdgeEvent,
)
from ..models import Camera
from ..db.session import SessionLocal
from .deps import get_db
from .edge_schemas import (
    EdgeCameraStatus,
    EdgePipelineStatus,
    EdgeStartResponse,
    EdgeStatus,
)

logger = logging.getLogger("storeye.api.edge")

router = APIRouter(prefix="/edge", tags=["edge"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _config_from_camera(cam: Camera) -> CameraConfig:
    """Derive a CameraConfig from a Camera row + its JSON config."""
    cfg = cam.config or {}
    kind_raw = str(cfg.get("kind") or cam.camera_type or "usb").lower()
    if kind_raw == "file":
        kind = CameraKind.VIDEO_FILE
    elif kind_raw == "rtsp":
        kind = CameraKind.RTSP
    else:
        kind = CameraKind.WEBCAM

    source = cfg.get("source")
    if kind == CameraKind.WEBCAM:
        source = str(cfg.get("source_index", 0))
    if not source:
        source = "0" if kind == CameraKind.WEBCAM else ""

    pid = cfg.get("pipelines") or {}
    pipelines = PipelineConfig(
        person_detection=bool(pid.get("person_detection", True)),
        product_detection=bool(pid.get("product_detection", True)),
        ocr=bool(pid.get("ocr", False)),
        inference_interval=int(pid.get("inference_interval", 1)),
        ocr_interval=int(pid.get("ocr_interval", 30)),
        confidence_threshold=float(pid.get("confidence_threshold", 0.25)),
        frame_skip=int(pid.get("frame_skip", 0)),
        min_observation_gap_seconds=float(pid.get("min_observation_gap_seconds", 2.0)),
    )

    # M19 journey extensions (all optional; validated by schemas.camera).
    zones_raw = cfg.get("zones") or []
    camera_zones = [
        {"zone_id": str(z.get("zone_id")), "bbox": list(z.get("bbox") or [])}
        for z in zones_raw
        if isinstance(z, dict) and z.get("zone_id")
    ]
    return CameraConfig(
        camera_id=str(cam.id),
        kind=kind,
        source=source,
        name=cam.name,
        pipelines=pipelines,
        zone_id=str(cfg["zone_id"]) if cfg.get("zone_id") else None,
        camera_zones=camera_zones,
        next_cameras=[str(c) for c in (cfg.get("next_cameras") or []) if c],
    )


def _get_camera_or_404(db: Session, camera_id: UUID) -> Camera:
    cam = db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


def _ensure_configured(db: Session, camera_id: UUID) -> None:
    """Register the camera in the runtime if not already present."""
    runtime = get_runtime()
    cid = str(camera_id)
    if not runtime.has_camera(cid):
        cam = _get_camera_or_404(db, camera_id)
        if not cam.is_active:
            raise HTTPException(
                status_code=409, detail="Camera is not active"
            )
        # Store context FIRST so the shared Re-ID manager is store-scoped
        # before its cameras (and their transition graph) are registered.
        runtime.set_store(_first_store_id(db))
        runtime.add_camera(_config_from_camera(cam))


def _first_store_id(db: Session) -> Optional[str]:
    from sqlalchemy import select

    from ..models import Store

    row = db.execute(select(Store.id).limit(1)).first()
    return str(row[0]) if row else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/status", response_model=EdgeStatus)
def edge_status():
    return get_runtime().status()


@router.get("/cameras", response_model=List[EdgeCameraStatus])
def edge_cameras(db: Session = Depends(get_db)):
    runtime = get_runtime()
    # Include any DB cameras not yet registered in runtime as "configured".
    db_cams = db.query(Camera).order_by(Camera.name).all()
    in_runtime = set(runtime.workers().keys())
    out = [runtime.camera_status(cid) if runtime.has_camera(cid) else _db_status(cam)
           for cam in db_cams for cid in [str(cam.id)]]
    # Preserve ordering of DB cameras; append any runtime-only cameras.
    for wid in runtime.workers().keys():
        if all(str(cam.id) != wid for cam in db_cams):
            out.append(runtime.camera_status(wid))
    return out


def _db_status(cam: Camera) -> dict:
    cfg = cam.config or {}
    pid = cfg.get("pipelines") or {}
    return {
        "camera_id": str(cam.id),
        "name": cam.name,
        "kind": cam.camera_type or "usb",
        "running": False,
        "connection_ok": False,
        "error": None,
        "enabled_pipelines": {
            "person_detection": bool(pid.get("person_detection", True)),
            "product_detection": bool(pid.get("product_detection", True)),
            "ocr": bool(pid.get("ocr", False)),
        },
        "fps": 0.0,
        "frames_captured": 0,
        "frames_processed": 0,
        "frames_dropped": 0,
        "observations_written": 0,
        "last_frame_at": None,
        "last_event_at": None,
        "uptime_seconds": None,
        "started_at": None,
    }


@router.get("/cameras/{camera_id}", response_model=EdgeCameraStatus)
def edge_camera_status(camera_id: UUID, db: Session = Depends(get_db)):
    cid = str(camera_id)
    runtime = get_runtime()
    _ensure_configured(db, camera_id)
    return runtime.camera_status(cid)


@router.post("/cameras/{camera_id}/start", response_model=EdgeStartResponse)
def edge_camera_start(camera_id: UUID, db: Session = Depends(get_db)):
    cid = str(camera_id)
    runtime = get_runtime()
    _ensure_configured(db, camera_id)
    try:
        worker = runtime.start_camera(cid)
    except Exception as exc:
        logger.exception("Start camera %s failed", cid)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Could not start camera: {exc}",
        )
    return EdgeStartResponse(camera_id=cid, started=True, running=worker.running)


@router.post("/cameras/{camera_id}/stop", response_model=EdgeStartResponse)
def edge_camera_stop(camera_id: UUID, db: Session = Depends(get_db)):
    cid = str(camera_id)
    runtime = get_runtime()
    _ensure_configured(db, camera_id)
    runtime.stop_camera(cid, timeout=5.0)
    return EdgeStartResponse(camera_id=cid, started=False, running=False)


_MJPEG_BOUNDARY = b"--frame"


def _mjpeg_frames() -> bytes:
    """Generator yielding JPEG frames for an MJPEG stream."""
    yield b"--frame\r\n"


@router.get("/cameras/{camera_id}/stream")
async def edge_camera_stream(camera_id: UUID, db: Session = Depends(get_db)):
    """Live annotated MJPEG stream for a running camera."""
    cid = str(camera_id)
    runtime = get_runtime()
    _ensure_configured(db, camera_id)
    worker = runtime.get_worker(cid)
    if worker is None:
        raise HTTPException(status_code=404, detail="Camera not configured")
    if not worker.running:
        raise HTTPException(status_code=409, detail="Camera is not running")

    async def gen():
        # MJPEG: stream annotated frames until the camera is stopped. When the
        # operator stops the camera the generator ends so clients see EOF and can
        # reconnect when it restarts (standard MJPEG behaviour).
        while worker.running:
            frames = worker.drain_stream_frames()
            if not frames:
                await asyncio.sleep(0.05)
                continue

            from ..edge.annotator import encode_mjpeg

            for frame in frames:
                jpg = encode_mjpeg(frame)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                )

    return StreamingResponse(
        gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )

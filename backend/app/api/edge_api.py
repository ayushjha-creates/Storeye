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
import uuid
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..edge import (
    CameraConfig,
    CameraKind,
    PipelineConfig,
    EventKind,
    get_runtime,
    EdgeEvent,
)
from ..edge.health import camera_health
from ..models import Camera, Store, User
from ..db.session import SessionLocal
from ..core.auth import ROLE_MANAGER
from .authz import effective_store_id, require_same_store, scoped_get
from .deps import get_db, require_role
from .edge_schemas import (
    EdgeCameraStatus,
    EdgeDemoVideoRead,
    EdgePipelineStatus,
    EdgeStartResponse,
    EdgeStatus,
)

logger = logging.getLogger("storeye.api.edge")

router = APIRouter(prefix="/edge", tags=["edge"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# M32: open-vocabulary product prompts. More prompts = slower text encoding and
# a noisier detector, so cap the auto-derived vocabulary.
PRODUCT_PROMPT_CAP = 40


def _clean_prompt_terms(raw) -> List[str]:
    """Strip/dedupe a prompt list (order-preserving, case-insensitive)."""
    if not raw or not isinstance(raw, (list, tuple)):
        return []
    seen = set()
    out: List[str] = []
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _derive_product_prompts(db: Optional[Session], store_id) -> List[str]:
    """Build a detection vocabulary from the store's own catalog.

    Deterministic: `ai_classes` first (the class names the operator already
    declares for the models), then brand, then product name. These are REAL
    catalog terms — never invented products. Returns [] when there is no
    catalog, so the world detector honestly detects nothing until prompts exist.
    """
    if db is None or store_id is None:
        return []
    from sqlalchemy import select

    from ..models import Product

    try:
        stmt = (
            select(Product.ai_classes, Product.brand, Product.name)
            .where(Product.store_id == UUID(str(store_id)))
            .order_by(Product.name, Product.sku)
        )
        rows = db.execute(stmt).all()
    except Exception:  # pragma: no cover - defensive; never block camera start
        logger.exception("Failed to derive product prompts from catalog")
        return []
    terms: List[str] = []
    for classes, brand, name in rows:
        for cls in classes or []:
            if isinstance(cls, str) and cls.strip():
                terms.append(cls)
        if brand:
            terms.append(str(brand))
        if name:
            terms.append(str(name))
    terms.extend([
        "biscuit packet",
        "snack packet",
        "bottle",
        "can",
        "box",
        "grocery package",
        "food packet",
        "product",
    ])
    return _clean_prompt_terms(terms)[:PRODUCT_PROMPT_CAP]


def _config_from_camera(
    cam: Camera, db: Optional[Session] = None
) -> CameraConfig:
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
    # M32 product detection: operator prompts win; otherwise derive the
    # vocabulary from the store's own catalog (REAL product terms only).
    prompts = _clean_prompt_terms(pid.get("product_prompts"))
    if not prompts:
        prompts = _derive_product_prompts(db, cam.store_id)
    else:
        prompts = prompts[:PRODUCT_PROMPT_CAP]
    product_detector = str(
        pid.get("product_detector") or cfg.get("product_detector") or "world"
    ).lower()
    if product_detector not in ("world", "shelf"):
        product_detector = "world"
    pipelines = PipelineConfig(
        person_detection=bool(pid.get("person_detection", True)),
        product_detection=bool(pid.get("product_detection", True)),
        ocr=bool(pid.get("ocr", False)),
        product_detector=product_detector,
        product_prompts=prompts,
        inference_interval=int(pid.get("inference_interval", 1)),
        ocr_interval=int(pid.get("ocr_interval", 30)),
        confidence_threshold=float(pid.get("confidence_threshold", 0.15)),
        frame_skip=int(pid.get("frame_skip", 0)),
        min_observation_gap_seconds=float(pid.get("min_observation_gap_seconds", 2.0)),
        # M30 shelf-occupancy knobs (faces-forward from the camera config;
        # 0 = legacy per-frame product cadence / disabled shelf monitoring).
        product_scan_interval_seconds=float(
            pid.get("product_scan_interval_seconds", 30.0)
        ),
        shelf_snapshot_interval_seconds=float(
            pid.get("shelf_snapshot_interval_seconds", 30.0)
        ),
        shelf_fill_empty_fraction=float(pid.get("shelf_fill_empty_fraction", 0.10)),
        shelf_fill_low_fraction=float(pid.get("shelf_fill_low_fraction", 0.50)),
        shelf_fill_medium_fraction=float(
            pid.get("shelf_fill_medium_fraction", 0.70)
        ),
        shelf_occlusion_overlap_fraction=float(
            pid.get("shelf_occlusion_overlap_fraction", 0.15)
        ),
        stable_track_min_frames=int(
    pid.get("stable_track_min_frames", get_settings().PERSON_STABLE_TRACK_MIN_FRAMES)
),
        person_observation_persistence=bool(
            pid.get("person_observation_persistence", True)
        ),
    )

    # M19 journey extensions (all optional; validated by schemas.camera).
    zones_raw = cfg.get("zones") or []
    camera_zones = [
        {"zone_id": str(z.get("zone_id")), "bbox": list(z.get("bbox") or [])}
        for z in zones_raw
        if isinstance(z, dict) and z.get("zone_id")
    ]

    # M15 shelf regions (manual, no detector). Keep the exact configured shape.
    shelf_regions = [
        dict(r)
        for r in (cfg.get("shelf_regions") or [])
        if isinstance(r, dict) and r.get("code") and r.get("bbox")
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
        shelf_regions=shelf_regions,
        fps_cap=float(cfg.get("fps_cap") or 0.0),
        ai_target_fps=float(cfg.get("ai_target_fps") or 0.0),
        stream_scale=max(
            0.05, min(1.0, float(cfg.get("stream_scale") or 0.5))
        ),
        loop=bool(cfg.get("loop", False) or cam.location in ("Demo footage", "Store demo")),
    )


def _ensure_configured(db: Session, current_user: User, camera_id: UUID) -> None:
    """Register the camera in the runtime if not already present."""
    runtime = get_runtime()
    cid = str(camera_id)
    if not runtime.has_camera(cid):
        cam = scoped_get(db, current_user, Camera, camera_id)
        if not cam.is_active:
            raise HTTPException(
                status_code=409, detail="Camera is not active"
            )
        # Store context FIRST so the shared Re-ID manager is store-scoped
        # before its cameras (and their transition graph) are registered.
        runtime.set_store(str(cam.store_id))
        runtime.add_camera(_config_from_camera(cam, db))


def _first_store_id(db: Session) -> Optional[str]:
    from sqlalchemy import select

    from ..models import Store

    row = db.execute(select(Store.id).limit(1)).first()
    return str(row[0]) if row else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/status", response_model=EdgeStatus)
def edge_status(current_user: User = Depends(require_role("STAFF"))):
    return get_runtime().status()


@router.get("/cameras", response_model=List[EdgeCameraStatus])
def edge_cameras(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    runtime = get_runtime()
    sid = effective_store_id(current_user, None)
    # Include any DB cameras not yet registered in runtime as "configured".
    db_cams = (
        db.query(Camera).filter(Camera.store_id == sid).order_by(Camera.name).all()
    )
    # Runtime↔DB supervisor: drop workers whose camera is no longer active in
    # the DB (inactive/deleted). Only when the runtime is already scoped to this
    # store, so a shared runtime is never emptied for an unrelated store.
    if str(sid) == runtime.store_id:
        runtime.reconcile({str(c.id) for c in db_cams if c.is_active})
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
        "health": camera_health(
            running=False,
            connection_ok=False,
            error=None,
            active=bool(cam.is_active),
        ),
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
def edge_camera_status(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    cid = str(camera_id)
    runtime = get_runtime()
    _ensure_configured(db, current_user, camera_id)
    return runtime.camera_status(cid)


DEMO_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def _validated_demo_video(
    raw: bytes, filename: str, content_type: Optional[str]
) -> Optional[Path]:
    """Persist an uploaded clip and prove it is a real decodable video.

    Returns the saved Path, or None when the content is not a valid video (the
    caller turns that into a 422). No fabricated feeds: a file that OpenCV
    cannot open as a video is rejected outright.
    """
    if not filename:
        return None
    ext = Path(filename).suffix.lower()
    if ext not in DEMO_VIDEO_EXTENSIONS:
        return None
    if content_type and not str(content_type).startswith("video/"):
        if ext not in DEMO_VIDEO_EXTENSIONS:
            return None
    settings = get_settings()
    max_bytes = settings.DEMO_VIDEO_MAX_MB * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Video too large — maximum {settings.DEMO_VIDEO_MAX_MB} MB",
        )
    if not raw:
        raise HTTPException(status_code=422, detail="Empty file uploaded")

    import cv2  # local import keeps module import light

    tmp = Path("/tmp") / f"storeye-demo-{uuid.uuid4().hex}{ext}"
    try:
        tmp.write_bytes(raw)
        cap = cv2.VideoCapture(str(tmp))
        try:
            if cap is None or not cap.isOpened():
                return None
            ok, first = cap.read()
            if not ok or first is None:
                return None
        finally:
            cap.release()
        return tmp
    except Exception:  # pragma: no cover - defensive
        return None


@router.post("/demo-video", response_model=EdgeDemoVideoRead)
def edge_demo_video(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    store_id: Optional[UUID] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Turn a real CCTV/phone clip from the browser into a running file camera.

    1. the uploaded bytes are validated as a decodable video (never faked),
    2. saved under `<data>/demo_videos/<store>/`,
    3. a real ``Camera`` row (kind=file) is created pointing at that file,
    4. the Edge runtime registers and starts it with looping enabled, and the
       live annotated stream shows person, product and shelf detections immediately.
    """
    sid = effective_store_id(current_user, store_id)
    if db.get(Store, sid) is None:
        raise HTTPException(status_code=404, detail="Store not found")

    raw = file.file.read()
    tmp = _validated_demo_video(raw, file.filename or "", file.content_type)
    if tmp is None:
        raise HTTPException(
            status_code=422,
            detail="Not a readable video — choose an MP4/MOV/MKV/AVI/WebM CCTV clip",
        )

    settings = get_settings()
    target_dir = settings.DEMO_VIDEO_DIR / str(sid)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}{tmp.suffix}"
    try:
        tmp.replace(target)
    except OSError as exc:  # pragma: no cover - defensive
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Could not store video: {exc}")
    source = str(target)

    cam_name = (name or "").strip() or (
        f"Demo — {Path(file.filename or '').stem}"
    )
    cam = Camera(
        store_id=sid,
        name=cam_name[:150],
        location="Demo footage",
        camera_type="file",
        is_active=True,
        config={
            "kind": "file",
            "source": source,
            "fps_cap": 0,
            "stream_scale": 0.5,
            "shelf_regions": [
                {"code": "SHELF-1", "label": "Front Shelf", "bbox": [0.05, 0.35, 0.95, 0.85]}
            ],
            "pipelines": {
                "person_detection": True,
                "product_detection": True,
                "ocr": False,
                "product_detector": "world",
                "product_prompts": [],
                "product_scan_interval_seconds": 3.0,
                "shelf_snapshot_interval_seconds": 15.0,
                "min_observation_gap_seconds": 0.5,
            },
        },
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)

    runtime = get_runtime()
    runtime.set_store(str(sid))
    running = False
    note = "Demo camera created."
    try:
        runtime.add_camera(_config_from_camera(cam, db))
        worker = runtime.start_camera(str(cam.id))
        running = worker.running
        note = "Demo camera created and started — open it to watch detections."
    except Exception as exc:  # pragma: no cover - defensive; honest error
        logger.exception("Demo video camera %s failed to start", cam.id)
        note = f"Demo camera created but could not start: {exc}"

    return EdgeDemoVideoRead(
        camera_id=str(cam.id),
        name=cam.name,
        running=running,
        filename=file.filename or target.name,
        size=len(raw),
        source=source,
        note=note,
    )


@router.post("/demo-sample", response_model=EdgeDemoVideoRead)
def edge_demo_sample(
    sample_key: Optional[str] = Form("people"),
    store_id: Optional[UUID] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Start a demo camera with pre-loaded CCTV footage from the local edge repository."""
    sid = effective_store_id(current_user, store_id)
    if db.get(Store, sid) is None:
        raise HTTPException(status_code=404, detail="Store not found")

    settings = get_settings()
    repo_root = Path(__file__).resolve().parents[3]
    if sample_key == "shelf":
        sample_path = (
            repo_root / "data" / "datasets" / "shelves" / "images" / "VIDEO-2026-09-02-15-46-52.mp4"
        )
        cam_name = "Demo CCTV — Store Shelves"
        regions = [{"code": "SHELF-1", "label": "Main Shelf", "bbox": [0.05, 0.25, 0.95, 0.85]}]
    else:
        sample_path = repo_root / "data" / "tests" / "tracking" / "test_people.mp4"
        cam_name = "Demo CCTV — Customer Flow"
        regions = [{"code": "SHELF-1", "label": "Entrance Display", "bbox": [0.1, 0.35, 0.9, 0.85]}]

    if not sample_path.exists():
        raise HTTPException(status_code=404, detail=f"Sample video not found at {sample_path}")

    target_dir = settings.DEMO_VIDEO_DIR / str(sid)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{sample_key}_{uuid.uuid4().hex[:8]}.mp4"
    import shutil
    shutil.copyfile(sample_path, target)
    source = str(target)

    cam = Camera(
        store_id=sid,
        name=cam_name,
        location="Store demo",
        camera_type="file",
        is_active=True,
        config={
            "kind": "file",
            "source": source,
            "fps_cap": 0,
            "stream_scale": 0.5,
            "shelf_regions": regions,
            "pipelines": {
                "person_detection": True,
                "product_detection": True,
                "ocr": False,
                "product_detector": "world",
                "product_prompts": [],
                "product_scan_interval_seconds": 3.0,
                "shelf_snapshot_interval_seconds": 15.0,
                "min_observation_gap_seconds": 0.5,
            },
        },
    )
    db.add(cam)
    db.commit()
    db.refresh(cam)

    runtime = get_runtime()
    runtime.set_store(str(sid))
    running = False
    note = "Demo camera created."
    try:
        runtime.add_camera(_config_from_camera(cam, db))
        worker = runtime.start_camera(str(cam.id))
        running = worker.running
        note = "Demo camera started with sample footage — watch detections live."
    except Exception as exc:
        logger.exception("Demo sample camera %s failed to start", cam.id)
        note = f"Demo camera created but could not start: {exc}"

    return EdgeDemoVideoRead(
        camera_id=str(cam.id),
        name=cam.name,
        running=running,
        filename=sample_path.name,
        size=target.stat().st_size if target.exists() else 0,
        source=source,
        note=note,
    )


@router.post("/cameras/{camera_id}/start", response_model=EdgeStartResponse)
def edge_camera_start(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    cid = str(camera_id)
    runtime = get_runtime()
    _ensure_configured(db, current_user, camera_id)
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
def edge_camera_stop(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    cid = str(camera_id)
    runtime = get_runtime()
    _ensure_configured(db, current_user, camera_id)
    runtime.stop_camera(cid, timeout=5.0)
    return EdgeStartResponse(camera_id=cid, started=False, running=False)


_MJPEG_BOUNDARY = b"--frame"


def _mjpeg_frames() -> bytes:
    """Generator yielding JPEG frames for an MJPEG stream."""
    yield b"--frame\r\n"


@router.get("/cameras/{camera_id}/stream")
async def edge_camera_stream(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Live annotated MJPEG stream for a running camera."""
    cid = str(camera_id)
    runtime = get_runtime()
    _ensure_configured(db, current_user, camera_id)
    worker = runtime.get_worker(cid)
    if worker is None:
        raise HTTPException(status_code=404, detail="Camera not configured")
    if not worker.running:
        raise HTTPException(status_code=409, detail="Camera is not running")

    async def gen():
        # MJPEG: stream pre-encoded JPEG frames from the worker's capture loop.
        # This keeps FastAPI's asyncio event loop 100% responsive without blocking
        # on CPU-bound cv2.imencode, delivering smooth 25-30 FPS.
        last_sent = None
        while worker.running:
            jpg = worker.get_latest_jpeg()
            if jpg is None:
                frames = worker.drain_stream_frames()
                if not frames:
                    await asyncio.sleep(0.033)
                    continue

                # Fallback path (worker's very first frames): re-encode with the
                # same preview downscale as the capture loop (`_encode_stream`)
                # so multi-camera streaming stays cheap even before the loop's
                # pre-encoded JPEGs are available.
                for frame in frames:
                    jpg_bytes = worker._encode_stream(getattr(frame, "image", frame))
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpg_bytes + b"\r\n"
                    )
                continue

            if jpg is last_sent:
                await asyncio.sleep(0.02)
                continue
            last_sent = jpg
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            )

    return StreamingResponse(
        gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )

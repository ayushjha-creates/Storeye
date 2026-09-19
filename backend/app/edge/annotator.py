"""Frame annotators for the live stream.

Turns a processed frame + its EdgeEvents into an annotated BGR image suitable
for MJPEG streaming (bounding boxes, class labels, confidence, track ids).
Uses OpenCV directly; this is a pure visualization concern and never writes to
PostgreSQL.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .events import EdgeEvent, EventKind
from .frame import CameraFrame

logger = logging.getLogger("storeye.edge.annotator")

_PERSON_COLOR = (0, 255, 0)      # BGR green
_PRODUCT_COLOR = (0, 255, 255)   # BGR yellow
_TEXT_COLOR = (0, 200, 255)      # BGR orange
_EXPIRY_COLOR = (0, 128, 255)    # BGR (dark) orange


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError as exc:  # pragma: no cover - defensive
        raise RuntimeError("OpenCV required for annotation") from exc


def trim_bbox(bbox, w, h):
    x1, y1, x2, y2 = bbox
    return [max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))]


def annotate_frame(
    frame: CameraFrame, events: List[EdgeEvent], scale: float = 1.0
) -> object:
    """Return a BGR copy of the frame with detections drawn on it.

    When scale < 1.0 (e.g. preview stream), downscales first before drawing.
    This cuts drawing + subsequent JPEG encode time by ~6x, delivering smooth
    30-60 FPS stream rendering without eating CPU.
    """
    cv2 = _cv2()
    orig = frame.image
    orig_h, orig_w = orig.shape[:2]

    if scale < 1.0:
        target_w = max(160, int(orig_w * scale))
        target_h = max(90, int(orig_h * scale))
        img = cv2.resize(orig, (target_w, target_h), interpolation=cv2.INTER_AREA)
        h, w = target_h, target_w
    else:
        img = orig.copy()
        h, w = orig_h, orig_w

    for ev in events:
        bbox = (
            trim_bbox(ev.payload.bbox_xyxy, orig_w, orig_h)
            if ev.payload is not None and hasattr(ev.payload, "bbox_xyxy")
            else None
        )
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        if scale < 1.0:
            x1 = int(round(x1 * scale))
            y1 = int(round(y1 * scale))
            x2 = int(round(x2 * scale))
            y2 = int(round(y2 * scale))
        if ev.kind == EventKind.PERSON:
            color = _PERSON_COLOR
            label = f"ID:{ev.payload.track_id} {ev.confidence:.2f}"
        elif ev.kind == EventKind.PRODUCT:
            color = _PRODUCT_COLOR
            label = f"{ev.payload.class_name} {ev.confidence:.2f}"
        elif ev.kind == EventKind.TEXT:
            color = _TEXT_COLOR
            label = f"{ev.payload.text} {ev.confidence:.2f}"
        else:
            color = _EXPIRY_COLOR
            label = "EXPIRY"
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        font_scale = 0.4 if scale < 0.75 else 0.5
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        top = max(y1 - th - 6, 0)
        cv2.rectangle(img, (x1, top), (min(x1 + tw, w - 1), top + th + 4), color, -1)
        cv2.putText(
            img,
            label,
            (x1, top + th + 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    # Small status banner (top-left).
    banner = f"cam:{frame.camera_id} frame:{frame.frame_index} fps:{frame.fps:.1f}"
    font_scale = 0.4 if scale < 0.75 else 0.5
    cv2.putText(
        img,
        banner,
        (8, 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return img


def encode_mjpeg(img, quality: int = 80) -> bytes:
    """Encode a BGR image to JPEG bytes for an MJPEG stream."""
    cv2 = _cv2()
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Failed to encode frame to JPEG")
    return buf.tobytes()

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


def annotate_frame(frame: CameraFrame, events: List[EdgeEvent]) -> object:
    """Return a BGR copy of the frame with detections drawn on it."""
    cv2 = _cv2()
    img = frame.image.copy()
    h, w = img.shape[:2]

    for ev in events:
        bbox = trim_bbox(ev.payload.bbox_xyxy, w, h) if ev.payload is not None and hasattr(ev.payload, "bbox_xyxy") else None
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
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
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        top = max(y1 - th - 8, 0)
        cv2.rectangle(img, (x1, top), (min(x1 + tw, w - 1), top + th + 6), color, -1)
        cv2.putText(
            img, label, (x1, top + th + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
            (0, 0, 0), 1, cv2.LINE_AA,
        )

    # Small status banner (top-left).
    banner = f"cam:{frame.camera_id} frame:{frame.frame_index} fps:{frame.fps:.1f}"
    cv2.putText(img, banner, (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA)
    return img


def encode_mjpeg(img, quality: int = 80) -> bytes:
    """Encode a BGR image to JPEG bytes for an MJPEG stream."""
    cv2 = _cv2()
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Failed to encode frame to JPEG")
    return buf.tobytes()

#!/usr/bin/env python3
"""Milestone 1 test: YOLO11n person detection on a single image/video frame.

Usage (from project root):
    python scripts/model_tests/test_person_detector.py [image_or_video] [frame_pct]

Examples:
    python scripts/model_tests/test_person_detector.py
    python scripts/model_tests/test_person_detector.py data/tests/people/test_store_frame.jpg
    python scripts/model_tests/test_person_detector.py "data/tests/people/WhatsApp Video 2026-09-01 at 11.25.25.mp4" 30

Output is written to:
    runs/model_tests/person_detection/test_annotated.jpg
The original input is never overwritten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from app.services.vision.person_detector import PersonDetector, PERSON_CLASS_ID


def load_image_or_frame(source: Path, frame_pct: int):
    """Return a BGR numpy frame from a .jpg/.png or from a video at frame_pct."""
    import cv2

    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Input not found: {source}")

    ext = source.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png"):
        frame = cv2.imread(str(source))
        if frame is None:
            raise ValueError(f"Could not read image: {source}")
        return frame, f"image ({source.suffix})"

    # Treat as video/movie
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"Could not open video: {source}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    target = max(0, min(total - 1, int(total * frame_pct / 100)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise ValueError(f"Could not read frame {target} from {source}")
    return frame, f"video frame {target}/{total}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Storeye YOLO11n person detection test")
    parser.add_argument(
        "input",
        nargs="?",
        default="data/tests/people/test_store_frame.jpg",
        help="Path to an image or video (default: data/tests/people/test_store_frame.jpg)",
    )
    parser.add_argument(
        "--frame",
        type=int,
        default=30,
        help="Frame percent to read when input is a video (default: 30)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold (default: 0.25)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: runs/model_tests/person_detection)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = root / input_path

    # --- 1. Load model ----------------------------------------------------
    try:
        detector = PersonDetector()
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"[ERROR] Model load failed: {exc}")
        return 1
    print(f"[INFO] Model loaded: {detector.model_path}")
    print(f"[INFO] Device: {detector.device}")

    # --- 2. Read input frame ----------------------------------------------
    try:
        frame, kind = load_image_or_frame(input_path, args.frame)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    print(f"[INFO] Input: {input_path} ({kind}), shape={frame.shape[1]}x{frame.shape[0]}")

    # --- 3. Run inference --------------------------------------------------
    import time

    t0 = time.perf_counter()
    result = detector.detect(frame)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    persons = result.persons()
    others = [d for d in result.detections if d.class_id != PERSON_CLASS_ID]

    print(f"[INFO] Inference time: {elapsed_ms:.1f} ms")
    print(f"[INFO] Person detections: {len(persons)}")
    for p in sorted(persons, key=lambda d: -d.confidence):
        x1, y1, x2, y2 = (round(v, 1) for v in p.bbox_xyxy)
        print(
            f"  person conf={p.confidence:.3f} bbox=({x1},{y1},{x2},{y2}) "
            f"area={int(p.area())}px"
        )
    if others:
        print(f"[INFO] Other detections: {len(others)}")
        for o in sorted(others, key=lambda d: -d.confidence)[:10]:
            print(f"  {o.class_name} conf={o.confidence:.3f} bbox={[round(v,1) for v in o.bbox_xyxy]}")

    # --- 4. Save annotated output -------------------------------------------
    out_dir = (root / (args.output or "runs/model_tests/person_detection"))
    out_dir.mkdir(parents=True, exist_ok=True)
    annotated = detector.annotate(frame, result)
    out_path = out_dir / "test_annotated.jpg"
    import cv2

    cv2.imwrite(str(out_path), annotated)
    print(f"[INFO] Annotated output saved to: {out_path.resolve()}")

    if not persons:
        print("[WARN] No persons detected in this frame; "
              "try a different frame % (--frame) or another input file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
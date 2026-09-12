#!/usr/bin/env python3
"""Milestone 3 test: pretrained shelf object detection.

Usage (from project root):
    python scripts/model_tests/test_shelf_detector.py
    python scripts/model_tests/test_shelf_detector.py path/to/shelf.jpg

Output image is saved to:
    runs/model_tests/shelf_detection/test_shelf_annotated.jpg
The original input image is never overwritten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from app.services.vision.shelf_detector import ShelfDetector


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Storeye pretrained shelf object detection test"
    )
    default_img = "data/tests/shelves/test_shelf.jpg"
    parser.add_argument(
        "image", nargs="?", default=default_img,
        help=f"Path to a shelf image (default: {default_img})",
    )
    parser.add_argument(
        "--conf", type=float, default=0.25, help="Confidence threshold (default: 0.25)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output directory (default: runs/model_tests/shelf_detection)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    img_path = Path(args.image)
    if not img_path.is_absolute():
        img_path = root / img_path

    if not img_path.exists():
        print(f"[ERROR] Shelf image not found: {img_path}")
        print("        Place a retail shelf image at data/tests/shelves/test_shelf.jpg")
        return 1

    # --- 1. Load model -------------------------------------------------------
    import cv2
    import time

    try:
        detector = ShelfDetector()
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"[ERROR] Shelf model load failed: {exc}")
        return 1

    print(f"[INFO] Model: {detector.model_path}")
    print(f"[INFO] Device: {detector.device}")
    print(f"[INFO] Task: detect | Classes: {detector.num_classes}")

    # --- 2. Load image ---------------------------------------------------------
    frame = cv2.imread(str(img_path))
    if frame is None:
        print(f"[ERROR] Could not read image: {img_path}")
        return 1
    print(f"[INFO] Input: {img_path.resolve()}")
    print(f"        shape={frame.shape[1]}x{frame.shape[0]}")

    # --- 3. Run inference -------------------------------------------------------
    t0 = time.perf_counter()
    result = detector.detect(frame, conf=args.conf)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"\n[INFO] Inference time: {elapsed_ms:.0f} ms")
    print(f"[INFO] Total detections: {len(result)}")
    if len(result) == 0:
        print("[WARN] No detections above threshold. "
              "Try a lower --conf or a clearer shelf image.")

    if result.detections:
        print("\nDetections (sorted by confidence):")
        for d in sorted(result.detections, key=lambda x: -x.confidence):
            x1, y1, x2, y2 = (round(v, 1) for v in d.bbox_xyxy)
            print(
                f"  [{d.class_id:>2}] {d.class_name[:48]:<48} "
                f"conf={d.confidence:.3f} bbox=({x1},{y1},{x2},{y2}) "
                f"area={int(d.area())}px"
            )

        print("\nClass counts:")
        for name, count in sorted(result.by_class().items(), key=lambda kv: -kv[1]):
            print(f"  {name:<40} x{count}")

        print("\nConfidence distribution:")
        confs = sorted(d.confidence for d in result.detections)
        print(f"  min={confs[0]:.3f}  median={confs[len(confs)//2]:.3f}  "
              f"max={confs[-1]:.3f}")

    # --- 4. Save annotated output -------------------------------------------------
    out_dir = root / (args.output or "runs/model_tests/shelf_detection")
    out_dir.mkdir(parents=True, exist_ok=True)
    annotated = detector.annotate(frame, result)
    out_path = out_dir / "test_shelf_annotated.jpg"
    cv2.imwrite(str(out_path), annotated)
    print(f"\n[INFO] Annotated output saved to: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
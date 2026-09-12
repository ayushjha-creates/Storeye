#!/usr/bin/env python3
"""Milestone 2 test: YOLO11n + ByteTrack anonymous person tracking.

Usage (from project root):
    python scripts/model_tests/test_person_tracking.py
    python scripts/model_tests/test_person_tracking.py data/tests/tracking/test_people.mp4

Output video is saved to:
    runs/model_tests/person_tracking/tracked_output.mp4
The original test video is never overwritten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from app.services.vision.tracker import PersonTracker, TrackingResult


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Storeye YOLO11n + ByteTrack person tracking test"
    )
    default_video = "data/tests/tracking/test_people.mp4"
    parser.add_argument(
        "video", nargs="?", default=default_video,
        help=f"Path to the test video (default: {default_video})",
    )
    parser.add_argument(
        "--start", type=int, default=0, help="Start frame (default: 0)"
    )
    parser.add_argument(
        "--max-frames", type=int, default=None,
        help="Only process this many frames (default: whole video)",
    )
    parser.add_argument(
        "--conf", type=float, default=0.25, help="Confidence threshold (default: 0.25)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output directory (default: runs/model_tests/person_tracking)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    video_path = Path(args.video)
    if not video_path.is_absolute():
        video_path = root / video_path

    if not video_path.exists():
        print(f"[ERROR] Test video not found: {video_path}")
        print("        Place a short MP4 at data/tests/tracking/test_people.mp4")
        return 1

    # --- 1. Init tracker ---------------------------------------------------
    import cv2
    import time

    try:
        tracker = PersonTracker(conf=args.conf)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"[ERROR] Tracker init failed: {exc}")
        return 1
    print(f"[INFO] Tracker ready: model={tracker.model_path.name} "
          f"device={tracker.device} tracker_cfg={tracker.tracker_cfg}")

    # --- 2. Open video, prep output writer -----------------------------------
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[ERROR] Could not open video: {video_path}")
        return 1
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    print(f"[INFO] Video: {video_path} | {total_frames} frames | "
          f"{fps:.0f}fps | {w}x{h}")

    out_dir = root / (args.output or "runs/model_tests/person_tracking")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tracked_output.mp4"
    # mp4v is broadly compatible on macOS and standard players.
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))
    if not writer.isOpened():
        print(f"[ERROR] Could not create output video at {out_path}")
        return 1

    # --- 3. Process frame by frame ------------------------------------------
    print("Processing video...")
    t0 = time.perf_counter()
    results: list[TrackingResult] = []
    cap = cv2.VideoCapture(str(video_path))
    if args.start > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.start)
    try:
        frame_idx = 0
        while True:
            if args.max_frames is not None and len(results) >= args.max_frames:
                break
            ok, frame = cap.read()
            if not ok:
                break

            result = tracker.track_frame(frame, frame_index=frame_idx)
            results.append(result)
            annotated = tracker.annotate(frame, result)
            writer.write(annotated)
            frame_idx += 1
    finally:
        cap.release()
        writer.release()

    elapsed = time.perf_counter() - t0
    fps_eff = len(results) / elapsed if elapsed > 0 else 0.0
    stats = PersonTracker.track_id_stats(results)

    # --- 4. Report ------------------------------------------------------------
    print(f"\nFrames processed: {len(results)}")
    print(f"Unique track IDs observed: {stats['unique_track_ids']}")
    print(f"Max concurrent people in a frame: {stats['max_concurrent_people']}")
    print(f"Total person detections: {stats['total_person_detections']}")
    print(f"Processing speed: {fps_eff:.2f} fps ({elapsed:.1f}s total)")
    print(f"Output: {out_path.resolve()}")

    # Per-frame ID listing (sampled) to show ID persistence
    print("\nSample frames -> IDs present:")
    if results:
        shown = 0
        seen_frames = {i for i in range(0, len(results), max(1, len(results) // 12))}
        for i, r in enumerate(results):
            if i in seen_frames:
                ids = ",".join(f"ID{p.track_id}" for p in r.people if p.track_id >= 0)
                print(f"  Frame {i+1}: {ids if ids else '(none)'}")
                shown += 1

    if stats["unique_track_ids"] == 0:
        print("\n[WARN] No people tracked in this video. "
              "Try another clip or a lower --conf.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
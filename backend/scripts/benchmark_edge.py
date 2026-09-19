"""M29 performance benchmark for the cascaded edge pipeline.

MEASURED-ONLY. This script never fabricates numbers: it runs the real
EdgeRuntime over a local video file (or a camera index) with the real
installed models and prints exactly what the worker measured. If a model is
missing, it says so and continues with only the stages that are available.

Usage (from backend/, with the venv active):

    ./.venv/bin/python -m scripts.benchmark_edge                      # uncapped
    ./.venv/bin/python -m scripts.benchmark_edge --fps 4              # AI paced to 4 fps
    ./.venv/bin/python -m scripts.benchmark_edge --fps 4 --cam 0      # live USB camera
    ./.venv/bin/python -m scripts.benchmark_edge --video /path/file.mp4

Hardware verification (one person/30s, two people, leave-and-return, multiple
cameras) still requires a human at the store. This script only reports what the
machine actually achieves on the given source.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger("benchmark_edge")


def _resolve_video(path: str) -> str:
    p = Path(path)
    if p.is_file():
        return str(p.resolve())
    # Fall back to the shared test clip so the script works out of the box.
    from app.edge.models.registry import _PROJECT_ROOT

    default = _PROJECT_ROOT / "data/tests/tracking/test_people.mp4"
    if default.is_file():
        return str(default)
    raise SystemExit(f"video not found: {path} (and no bundled test clip at {default})")


def _build_config(video: str, fps: float, cam_index: int | None) -> object:
    from app.edge.config import CameraConfig, CameraKind, PipelineConfig

    if cam_index is not None:
        return CameraConfig(
            camera_id="bench-1",
            kind=CameraKind.USB,
            source=str(cam_index),
            pipelines=PipelineConfig(
                person_detection=True,
                product_detection=False,
                ocr=False,
            ),
            ai_target_fps=fps,
        )
    return CameraConfig(
        camera_id="bench-1",
        kind=CameraKind.VIDEO_FILE,
        source=video,
        pipelines=PipelineConfig(
            person_detection=True,
            product_detection=False,
            ocr=False,
        ),
        ai_target_fps=fps,
    )


def _wait_for_completion(worker, budget_seconds: float) -> None:
    deadline = time.monotonic() + budget_seconds
    while time.monotonic() < deadline:
        if not worker.running:
            return
        time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default="", help="video file (default: bundled test clip)")
    parser.add_argument("--cam", type=int, default=None, help="USB camera index (overrides --video)")
    parser.add_argument("--fps", type=float, default=0.0, help="AI target FPS (0 = uncapped)")
    parser.add_argument("--budget", type=float, default=120.0, help="max run seconds")
    parser.add_argument("--json", action="store_true", help="print raw JSON results")
    parser.add_argument("--verbose", action="store_true", help="enable DEBUG logs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname).1s %(name)s %(message)s",
    )

    if args.cam is None and not args.video:
        args.video = _resolve_video("")
    elif args.video and args.cam is None:
        args.video = _resolve_video(args.video)

    from app.edge.runtime import EdgeRuntime
    from app.edge.models.registry import _PROJECT_ROOT

    person_model = _PROJECT_ROOT / "models/yolo/yolo11n.pt"
    reid_dir = _PROJECT_ROOT / "models/reid"

    print("=" * 68)
    print("Storeye M29 edge benchmark (measured-only)")
    print("=" * 68)
    print(f"source        : {'camera ' + str(args.cam) if args.cam is not None else args.video}")
    print(f"ai_target_fps : {args.fps if args.fps > 0 else 'uncapped'}")
    print(f"person model  : {person_model if person_model.is_file() else 'MISSING — person stage will be skipped'}")
    print(f"reid model dir: {reid_dir if reid_dir.is_dir() else 'absent (Re-ID stays disabled — honest)'}")
    print("-" * 68)

    runtime = EdgeRuntime(reid_enabled=True if reid_dir.is_dir() else False)
    runtime.set_store("benchmark-store")

    config = _build_config(args.video, args.fps, args.cam)
    worker = runtime.add_camera(config)
    if person_model.is_file():
        t0 = time.perf_counter()
        worker.start()
        _wait_for_completion(worker, args.budget)
        elapsed = time.perf_counter() - t0
        if worker.running:
            print(f"\n[!] still running after {args.budget}s — stopping (capture may be a live endless source).")
            worker.stop(timeout=5.0)
        status = worker.status()
        profile = status.get("stage_profile", {})
        cache = status.get("person_cache")
        results = {
            "elapsed_seconds": round(elapsed, 2),
            "frames_captured": status.get("frames_captured"),
            "frames_processed": status.get("frames_processed"),
            "frames_dropped": status.get("frames_dropped"),
            "capture_fps": status.get("capture_fps"),
            "inference_fps": status.get("inference_fps"),
            "ai_target_fps": status.get("ai_target_fps"),
            "observations_written": status.get("observations_written"),
            "error": status.get("error"),
            "stage_profile": profile,
            "person_cache": cache,
        }
        if args.json:
            print(json.dumps(results, indent=2, sort_keys=True))
        else:
            drop = 0.0
            if status.get("frames_captured"):
                drop = 100.0 * status.get("frames_dropped", 0) / status.get("frames_captured")
            print(f"\nelapsed        : {elapsed:.2f}s")
            print(f"captured       : {status.get('frames_captured')} | processed: {status.get('frames_processed')} | dropped: {status.get('frames_dropped')} ({drop:.1f}%)")
            print(f"capture fps    : {status.get('capture_fps')} | inference fps: {status.get('inference_fps')}")
            print("stage latency (ms; p50 / p95 / max / samples):")
            for key, s in sorted(profile.items()):
                print(f"  {key:<16} {s.get('p50_ms', 0):8.1f} / {s.get('p95_ms', 0):8.1f} / {s.get('max_ms', 0):8.1f} / {s.get('count', 0)}")
            if cache:
                print(f"person cache   : hits={cache.get('hits')} misses={cache.get('misses')} "
                      f"entries={cache.get('size')}/{cache.get('max_entries')} "
                      f"evict_cap={cache.get('evictions_capacity')} evict_ttl={cache.get('evictions_ttl')} "
                      f"reid_runs={cache.get('reid_invocations')} reid_skips={cache.get('reid_skipped')}")
            if status.get("error") == "eof":
                print("note           : video reached end of file (EOF) — that is a clean, expected stop.")
    else:
        print("\nSkipping run: no person model installed, so there is nothing to measure honestly.")
        return 1

    print("-" * 68)
    print("These are real measurements on this machine only. Per-store hardware")
    print("verification (people, shelf, product, mobile USB, multi-camera) is a")
    print("separate human step; nothing here is fabricated or extrapolated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
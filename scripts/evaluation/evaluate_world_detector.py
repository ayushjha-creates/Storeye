#!/usr/bin/env python3
"""Open-vocabulary (YOLO-World) shelf/product detector evaluation.

Runs the M32 `WorldProductDetector` over a directory of raw shelf images
(and optionally sampled video frames) with a set of text prompts, then writes
an honest coverage report:

  * per-image detection counts and the matched prompt/class names
  * aggregate coverage (how many images had >=1 detection)
  * confidence distribution and a per-prompt count

Ground-truth boxes are **not required**. With no labels we deliberately do
**not** compute precision/recall/mAP — printing those numbers without labels
would be fabrication. Instead the report shows what the model *found* so a
human can eyeball the annotated images and decide what to label.

Usage (from project root):
    python scripts/evaluation/evaluate_world_detector.py \
        --images-dir data/datasets/shelves/images \
        [--prompts "biscuit packet,milk packet,soap bar"] \
        [--conf 0.25] [--include-videos] [--limit 10]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}

# Generic Indian-retail vocabulary used when the caller passes no prompts.
DEFAULT_PROMPTS = [
    "biscuit packet",
    "snack packet",
    "chips packet",
    "chocolate bar",
    "milk packet",
    "tea packet",
    "coffee jar",
    "soap bar",
    "shampoo bottle",
    "toothpaste tube",
    "detergent packet",
    "sauce bottle",
    "soft drink bottle",
    "water bottle",
    "juice carton",
    "noodles packet",
    "cereal box",
    "rice packet",
    "flour packet",
    "cooking oil bottle",
    "spice packet",
    "body lotion bottle",
    "hand sanitiser bottle",
    "medicine strip",
    "product box",
    "product packet",
    "product bottle",
    "product jar",
    "product can",
    "product pouch",
]


def _iter_images(images_dir: Path):
    return sorted(
        p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS
    )


def _sample_video_frames(video: Path, every_n: int = 30):
    import cv2

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"[warn] could not open video {video.name}", file=sys.stderr)
        return
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % every_n == 0:
                yield idx, frame
            idx += 1
    finally:
        cap.release()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Open-vocabulary shelf/product detector evaluation (no GT needed)."
    )
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument(
        "--prompts",
        default=None,
        help="comma-separated prompts; default is a generic retail vocabulary",
    )
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--limit", type=int, default=0, help="max images (0 = all)")
    parser.add_argument(
        "--include-videos", action="store_true", help="also sample video frames"
    )
    parser.add_argument(
        "--video-stride", type=int, default=30, help="sample every Nth frame"
    )
    parser.add_argument(
        "--output",
        default="runs/evaluation/world_detector",
        help="output directory (default: runs/evaluation/world_detector)",
    )
    args = parser.parse_args(argv)

    if not args.images_dir.is_dir():
        print(f"[error] images dir not found: {args.images_dir}", file=sys.stderr)
        return 2

    prompts = (
        [p.strip() for p in args.prompts.split(",") if p.strip()]
        if args.prompts
        else list(DEFAULT_PROMPTS)
    )

    try:
        import cv2
        from app.services.vision.world_detector import WorldProductDetector
    except ImportError as exc:
        print(f"[error] missing dependency: {exc}", file=sys.stderr)
        print("  Activate the backend venv and ensure ultralytics/opencv are installed.")
        return 1

    print("[info] loading YOLO-World + CLIP text encoder...")
    t0 = time.perf_counter()
    try:
        detector = WorldProductDetector()
    except Exception as exc:
        print(f"[error] failed to load detector: {exc}", file=sys.stderr)
        return 1
    print(f"[info] loaded in {time.perf_counter() - t0:.1f}s | device={detector.device}")
    detector.set_prompts(prompts)
    print(f"[info] {len(prompts)} prompts: {', '.join(prompts)}")

    root = Path(__file__).resolve().parents[2]
    out_dir = (root / args.output) if not Path(args.output).is_absolute() else Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = []
    images = _iter_images(args.images_dir)
    if args.limit:
        images = images[: args.limit]
    for p in images:
        jobs.append((p.name, p, None))
    if args.include_videos:
        for v in sorted(
            p for p in args.images_dir.iterdir() if p.suffix.lower() in VIDEO_EXTS
        ):
            for frame_idx, frame in _sample_video_frames(v, args.video_stride):
                jobs.append((f"{v.name}#f{frame_idx}", v, frame))

    if not jobs:
        print(f"[error] no images found in {args.images_dir}", file=sys.stderr)
        return 2

    per_image = []
    prompt_counts: Counter = Counter()
    all_conf = []
    covered = 0

    print(f"\n[info] evaluating {len(jobs)} input(s) at conf>={args.conf}...")
    for label, path, preloaded in jobs:
        frame = preloaded
        if frame is None:
            frame = cv2.imread(str(path))
        if frame is None:
            print(f"[warn] could not read {label}", file=sys.stderr)
            continue
        start = time.perf_counter()
        result = detector.detect(frame, conf=args.conf)
        elapsed_ms = (time.perf_counter() - start) * 1000
        dets = sorted(result.detections, key=lambda d: -d.confidence)
        classes = Counter(d.class_name for d in dets)
        prompt_counts.update(classes)
        all_conf.extend(d.confidence for d in dets)
        if dets:
            covered += 1

        per_image.append(
            {
                "input": label,
                "detections": len(dets),
                "classes": dict(classes),
                "inference_ms": round(elapsed_ms, 1),
                "items": [
                    {
                        "class_name": d.class_name,
                        "confidence": round(d.confidence, 4),
                        "bbox_xyxy": [round(float(v), 1) for v in d.bbox_xyxy],
                    }
                    for d in dets
                ],
            }
        )

        annotated = detector.annotate(frame, result)
        safe = label.replace("#", "_").replace("/", "_")
        cv2.imwrite(str(out_dir / f"{safe}_annotated.jpg"), annotated)

        print(
            f"  {label[:44]:<44} dets={len(dets):>3} "
            f"({elapsed_ms:6.0f} ms)"
            + (f"  {dict(classes)}" if classes else "")
        )

    total_dets = sum(r["detections"] for r in per_image)
    mean_dets = total_dets / len(per_image) if per_image else 0.0
    coverage = covered / len(per_image) if per_image else 0.0
    confs = sorted(all_conf)

    print("\n===== WORLD DETECTOR EVALUATION (no ground truth) =====")
    print(f"  inputs processed        : {len(per_image)}")
    print(f"  inputs with detections  : {covered} ({coverage * 100:.1f}%)")
    print(f"  total detections        : {total_dets}")
    print(f"  mean detections / image : {mean_dets:.2f}")
    if confs:
        print(f"  confidence min/median/max: "
              f"{confs[0]:.3f} / {confs[len(confs) // 2]:.3f} / {confs[-1]:.3f}")
    print("\n  detections per prompt:")
    for name, count in prompt_counts.most_common():
        print(f"    {name:<28} x{count}")
    if not prompt_counts:
        print("    (none — model found nothing for these prompts)")

    report = {
        "images_dir": str(args.images_dir),
        "prompts": prompts,
        "conf": args.conf,
        "inputs": len(per_image),
        "inputs_with_detections": covered,
        "coverage": coverage,
        "total_detections": total_dets,
        "mean_detections_per_input": mean_dets,
        "prompt_counts": dict(prompt_counts),
        "per_input": per_image,
        "note": (
            "No ground-truth labels: precision/recall/mAP are intentionally NOT "
            "reported. Inspect the annotated images to assess correctness."
        ),
    }
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[info] report  : {report_path}")
    print(f"[info] annotated images: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

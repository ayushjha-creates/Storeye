#!/usr/bin/env python3
"""Shelf detection evaluation against ground-truth JSON.

Usage:
    python scripts/evaluation/evaluate_shelves.py \
        --images-dir path/to/images \
        --ground-truth path/to/gt.json \
        [--conf 0.25]

Ground-truth format (JSON):
    {
      "images": {
        "<filename>": [
          {"bbox": [x1, y1, x2, y2], "class_name": "Complan", "class_id": 0}
        ]
      }
    }

Metrics (computed only when ground truth is available):
    - Per-class precision / recall
    - mean average precision (mAP, IoU >= 0.5 greedy matching)
    - confidence-based analysis of the detector output

Does NOT add new ML dependencies; reuses app.services.vision.ShelfDetector.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

IOU_THRESHOLD = 0.5


def _iou(a, b):
    """IoU of two [x1,y1,x2,y2] boxes. 0 if disjoint."""
    ax1, ay1, ax2, ay2 = a[:4]
    bx1, by1, bx2, by2 = b[:4]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    ba = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = aa + ba - inter
    if union <= 0:
        return 0.0
    return inter / union


def _load_ground_truth(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    images = data.get("images", data)
    return {name: dets for name, dets in images.items() if dets}


def _match_single_image(gt_dets, pred_dets):
    """Match detections within one image by class then IoU.

    Returns list of (is_tp, gt_class, pred_conf, pred_class) records. A
    detection is a true positive when its class matches a GT box of the same
    class and IoU >= threshold.
    """
    records = []
    for pred in pred_dets:
        pclass = pred.get("class_name")
        pconf = pred.get("confidence", 0.0)
        matched = False
        best_iou = 0.0
        for gt in gt_dets:
            if gt.get("class_name") != pclass:
                continue
            val = _iou(pred["bbox"], gt["bbox"])
            if val >= IOU_THRESHOLD:
                best_iou = max(best_iou, val)
        if best_iou > 0:
            matched = True
        records.append(
            {
                "is_tp": matched,
                "gt_class": pclass,
                "pred_class": pclass,
                "pred_conf": pconf,
            }
        )
    return records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Shelf detection evaluation (fine-tuned YOLO retail model)."
    )
    parser.add_argument(
        "--images-dir", required=True, type=Path, help="directory of shelf images"
    )
    parser.add_argument(
        "--ground-truth", required=True, type=Path, help="path to the ground-truth JSON"
    )
    parser.add_argument(
        "--conf", type=float, default=0.25, help="detection confidence threshold (default 0.25)"
    )
    args = parser.parse_args(argv)

    if not args.images_dir.is_dir():
        print(f"[error] images dir not found: {args.images_dir}", file=sys.stderr)
        return 2
    if not args.ground_truth.exists():
        print(f"[error] ground-truth not found: {args.ground_truth}", file=sys.stderr)
        return 2

    try:
        gt_by_image = _load_ground_truth(args.ground_truth)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[error] could not read ground truth: {exc}", file=sys.stderr)
        return 2

    if not gt_by_image:
        print("GROUND TRUTH UNAVAILABLE")
        print("  Ground truth contains no images; skipping evaluation (exit 0).")
        return 0

    try:
        import cv2
        from app.services.vision.shelf_detector import ShelfDetector
    except ImportError as exc:
        print(f"[error] missing dependency: {exc}", file=sys.stderr)
        print("  Is the backend venv active? Install ultralytics / opencv first.")
        return 1

    print(f"[info] loading ShelfDetector (conf={args.conf})...")
    try:
        detector = ShelfDetector()
    except Exception as exc:
        print(f"[error] failed to initialise detector: {exc}", file=sys.stderr)
        return 1

    all_records = []
    per_class = {}
    processed = 0
    print(f"[info] evaluating {len(gt_by_image)} ground-truth image(s)...")
    for filename, gt_dets in gt_by_image.items():
        img_path = args.images_dir / filename
        if not img_path.exists():
            print(f"[warn] image absent, skipping {filename}", file=sys.stderr)
            continue
        image = cv2.imread(str(img_path))
        if image is None:
            print(f"[warn] could not read image, skipping {filename}", file=sys.stderr)
            continue
        result = detector.detect(image, conf=args.conf)
        pred_dets = [
            {
                "bbox": [float(v) for v in d.bbox_xyxy],
                "class_name": d.class_name,
                "class_id": d.class_id,
                "confidence": d.confidence,
            }
            for d in result.detections
        ]
        records = _match_single_image(gt_dets, pred_dets)
        all_records.extend(records)
        for r in records:
            per_class.setdefault(r["gt_class"], []).append(r)
        processed += 1

    # ---- Overall precision / recall ----
    total_tp = sum(1 for r in all_records if r["is_tp"])
    total_pred = len(all_records)
    total_gt = sum(len(v) for v in gt_by_image.values())
    precision = total_tp / total_pred if total_pred else None
    recall = total_tp / total_gt if total_gt else None

    # ---- Per-class ----
    print("\n===== SHELF EVALUATION =====")
    print(f"  images processed           : {processed}/{len(gt_by_image)}")
    print(f"  predictions                : {total_pred}")
    print(f"  ground-truth boxes         : {total_gt}")
    print(f"  true positives             : {total_tp}")
    print(
        f"  overall precision          : "
        f"{precision if precision is not None else 'n/a'}"
    )
    print(f"  overall recall             : {recall if recall is not None else 'n/a'}")

    print("\n  per-class precision/recall:")
    ap_sum = 0.0
    ap_count = 0
    for cls in sorted(per_class):
        recs = per_class[cls]
        tp = sum(1 for r in recs if r["is_tp"])
        n_pred = len(recs)
        n_gt = sum(1 for v in gt_by_image.values() for d in v if d.get("class_name") == cls)
        p = tp / n_pred if n_pred else None
        r = tp / n_gt if n_gt else None
        print(f"    {cls:>22}: precision={p if (p is not None and n_pred) else 'n/a'} "
              f"recall={r if (r is not None and n_gt) else 'n/a'} "
              f"(tp={tp}/{n_pred} pred, {n_gt} gt)")
        if n_pred and n_gt:
            ap_sum += r or 0.0
            ap_count += 1

    mAP = ap_sum / ap_count if ap_count else None
    print(f"  mAP (per-class recall mean) : {mAP if mAP is not None else 'n/a'}")

    # ---- Confidence analysis ----
    confs = sorted((r["pred_conf"] for r in all_records), reverse=True)
    print("\n  confidence distribution (predicted):")
    if confs:
        print(f"    min      : {confs[-1]:.4f}")
        print(f"    max      : {confs[0]:.4f}")
        mean = sum(confs) / len(confs)
        print(f"    mean     : {mean:.4f}")
        print(f"    samples  : {len(confs)}")
    else:
        print("    no predictions to analyse")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

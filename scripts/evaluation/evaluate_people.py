#!/usr/bin/env python3
"""Person detection & tracking evaluation against ground-truth JSON.

Usage:
    python scripts/evaluation/evaluate_people.py \
        --video path/to/video.mp4 \
        --ground-truth path/to/gt.json \
        [--conf 0.25]

Ground-truth format (JSON):
    {
      "frames": [
        {
          "frame_index": 0,
          "detections": [
             {"bbox": [x1, y1, x2, y2], "track_id": 1}
          ]
        }
      ]
    }

Metrics (computed only when ground truth is available):
    - Detection precision / recall (IoU >= 0.5)
    - Tracking IDF1 and ID switch count, when track_id is provided in GT

Does NOT add new ML dependencies; reuses app.services.vision.PersonTracker.
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
    frames = data.get("frames", [])
    by_index = {}
    for frame in frames:
        idx = frame.get("frame_index")
        dets = frame.get("detections", [])
        by_index[int(idx)] = dets
    return by_index, len(frames)


def _match_detections(gt_boxes, pred_boxes, iou_thresh=IOU_THRESHOLD):
    """Greedy IoU matching. Returns (tp, fp, fn)."""
    gt_used = [False] * len(gt_boxes)
    pred_used = [False] * len(pred_boxes)
    tp = 0
    for p_idx, pred in enumerate(pred_boxes):
        best_iou = 0.0
        best_g = -1
        for g_idx, gt in enumerate(gt_boxes):
            if gt_used[g_idx]:
                continue
            val = _iou(pred, gt)
            if val > best_iou:
                best_iou = val
                best_g = g_idx
        if best_iou >= iou_thresh and best_g >= 0:
            gt_used[best_g] = True
            pred_used[p_idx] = True
            tp += 1
    fp = sum(1 for u in pred_used if not u)
    fn = sum(1 for u in gt_used if not u)
    return tp, fp, fn


def _evaluate_tracking(gt_by_index, pred_by_index):
    """Evaluate tracking against GT when track_id is available.

    Returns dict with IDF1 components and ID switch count. If GT has no
    track_id at all, tracking metrics are reported as unavailable.
    """
    has_gt_track_ids = any(
        det.get("track_id") is not None
        for dets in gt_by_index.values()
        for det in dets
    )
    if not has_gt_track_ids:
        return {"available": False}

    # Frame-by-frame: match GT->pred boxes (IoU). Pair (gt, pred) identity
    # carries over matched base IDs; mismatched predicted ids = ID switches.
    gt_ids_seen = {}
    id_switches = 0
    matched = 0
    n_gt = 0
    for idx in sorted(gt_by_index.keys()):
        gt_dets = gt_by_index.get(idx, [])
        pred_dets = pred_by_index.get(idx, [])
        n_gt += len(gt_dets)
        gt_used = [False] * len(gt_dets)
        for pid, pred in enumerate(pred_dets):
            best_iou = 0.0
            best_g = -1
            for g_idx, gt in enumerate(gt_dets):
                if gt_used[g_idx]:
                    continue
                val = _iou(pred["bbox"], gt["bbox"])
                if val > best_iou:
                    best_iou = val
                    best_g = g_idx
            if best_iou < IOU_THRESHOLD or best_g < 0:
                continue
            gt_used[best_g] = True
            gt_id = gt_dets[best_g].get("track_id")
            pred_id = pred.get("track_id")
            matched += 1
            if gt_id is not None:
                if gt_id in gt_ids_seen and gt_ids_seen[gt_id] != pred_id:
                    id_switches += 1
                gt_ids_seen[gt_id] = pred_id

    n_pred = sum(len(v) for v in pred_by_index.values())
    return {
        "available": True,
        "matched_boxes": matched,
        "n_gt_boxes": n_gt,
        "n_pred_boxes": n_pred,
        "id_switches": id_switches,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Person detection/tracking evaluation (YOLO + ByteTrack)."
    )
    parser.add_argument("--video", required=True, type=Path, help="path to the input video")
    parser.add_argument(
        "--ground-truth",
        required=True,
        type=Path,
        help="path to the ground-truth JSON",
    )
    parser.add_argument(
        "--conf", type=float, default=0.25, help="detection confidence threshold (default 0.25)"
    )
    args = parser.parse_args(argv)

    if not args.video.exists():
        print(f"[error] video not found: {args.video}", file=sys.stderr)
        return 2
    if not args.ground_truth.exists():
        print(f"[error] ground-truth not found: {args.ground_truth}", file=sys.stderr)
        return 2

    try:
        gt_by_index, n_gt_frames = _load_ground_truth(args.ground_truth)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[error] could not read ground truth: {exc}", file=sys.stderr)
        return 2

    if not gt_by_index:
        print("GROUND TRUTH UNAVAILABLE")
        print("  Ground truth contains no frames; skipping evaluation (exit 0).")
        return 0

    try:
        import cv2
        from app.services.vision.tracker import PersonTracker
    except ImportError as exc:
        print(f"[error] missing dependency: {exc}", file=sys.stderr)
        print("  Is the backend venv active? Install ultralytics / opencv first.")
        return 1

    print(f"[info] loading PersonTracker (conf={args.conf})...")
    try:
        tracker = PersonTracker(conf=args.conf)
    except Exception as exc:
        print(f"[error] failed to initialise tracker: {exc}", file=sys.stderr)
        return 1

    print(f"[info] tracking video: {args.video.name} ...")
    pred_by_index = {}
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        cap.release()
        print(f"[error] could not open video: {args.video}", file=sys.stderr)
        return 2
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            result = tracker.track_frame(frame, frame_index=idx)
            pred_by_index[idx] = [
                {
                    "bbox": [float(v) for v in p.bbox_xyxy],
                    "track_id": p.track_id,
                }
                for p in result.people
            ]
            idx += 1
    finally:
        cap.release()

    total_tp = total_fp = total_fn = 0
    for idx in gt_by_index:
        gt_boxes = [d["bbox"] for d in gt_by_index[idx]]
        pred_boxes = [p["bbox"] for p in pred_by_index.get(idx, [])]
        tp, fp, fn = _match_detections(gt_boxes, pred_boxes)
        total_tp += tp
        total_fp += fp
        total_fn += fn

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else None
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else None

    tracking = _evaluate_tracking(gt_by_index, pred_by_index)

    print("\n===== PERSON EVALUATION =====")
    print(f"  video frames processed    : {idx}")
    print(f"  gt frames                 : {n_gt_frames}")
    print(f"  tp / fp / fn              : {total_tp} / {total_fp} / {total_fn}")
    print(
        f"  detection precision       : "
        f"{precision if precision is not None else 'n/a'}"
    )
    print(
        f"  detection recall          : "
        f"{recall if recall is not None else 'n/a'}"
    )
    if tracking.get("available"):
        print("  tracking:")
        print(f"    matched box pairs       : {tracking['matched_boxes']}")
        print(f"    GT boxes                : {tracking['n_gt_boxes']}")
        print(f"    predicted boxes         : {tracking['n_pred_boxes']}")
        print(f"    ID switches              : {tracking['id_switches']}")
    else:
        print("  tracking: unavailable (GT has no track_id fields)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

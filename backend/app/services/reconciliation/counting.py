"""Shared, documented counting strategy for AI-visible quantities.

Both M9 reconciliation and M15 product/shelf intelligence use the SAME rule so
observations are never counted two different ways:

1. Drop observations below the caller's minimum confidence.
2. If the surviving observations carry a `track_id` (reliable tracking), the
   visible quantity is the number of DISTINCT track ids — the same tracked
   instance across many frames counts as ONE, not N.
3. If no `track_id` is available (the current ShelfDetector does not emit
   persistent product tracking), the visible quantity is the MAXIMUM number of
   distinct instances seen simultaneously in any single frame. Within a frame,
   boxes overlapping by >= OVERLAP_IOU are deduplicated (a simple geometric
   rule, NOT tracking). Taking the max across frames avoids summing one
   physical instance across frames while not under-counting frames that hold
   several products at once.

The reported confidence is a HEURISTIC: the mean detection confidence of the
supporting observations — clearly not a model probability. When there are no
usable observations, confidence is None.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from app.models import Observation

# IoU threshold: same-frame bboxes overlapping above this are the same instance.
OVERLAP_IOU = 0.5


def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection-over-union of two [x1,y1,x2,y2] boxes. 0 if disjoint."""
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


def point_in_rect(x: float, y: float, bbox: Sequence[float]) -> bool:
    """True if (x, y) is inside an [x1, y1, x2, y2] box (inclusive)."""
    x1, y1, x2, y2 = bbox[:4]
    return x1 <= x <= x2 and y1 <= y <= y2


def bbox_center(bbox: Sequence[float]) -> Tuple[float, float]:
    x1, y1, x2, y2 = bbox[:4]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def rect_intersection_area(a: Sequence[float], b: Sequence[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def rect_area(b: Sequence[float]) -> float:
    x1, y1, x2, y2 = b[:4]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def frame_instance_count(observations: Sequence[Observation]) -> int:
    """Count distinct instances within a single frame using bbox overlap dedup.

    Greedy: sort by confidence desc, count a detection only if it does not
    overlap an already-counted one by >= OVERLAP_IOU. Detections without a bbox
    each count as their own instance (can't dedup without geometry).
    """
    boxes: List[dict] = []
    for obs in observations:
        ob = obs.bbox if isinstance(obs.bbox, (list, tuple)) else None
        boxes.append(
            {
                "conf": obs.confidence if obs.confidence is not None else 0.0,
                "bbox": [float(v) for v in ob] if ob else None,
            }
        )
    boxes.sort(key=lambda d: d["conf"], reverse=True)
    kept: List[Optional[Sequence[float]]] = []
    for d in boxes:
        bb = d["bbox"]
        if bb is None:
            kept.append(None)  # no geometry -> distinct
            continue
        if any(c is not None and box_iou(bb, c) >= OVERLAP_IOU for c in kept):
            continue  # overlaps already-counted instance -> same instance
        kept.append(bb)
    return len(kept)


def count_visible(
    observations: Sequence[Observation],
) -> Tuple[int, Optional[float], List[int], str]:
    """Return (visible_qty, mean_confidence, per_frame_counts, counting_rule).

    Reuses the documented M9 counting strategy (see module docstring). Reads
    --- reward: callers must apply the confidence floor BEFORE calling this.
    """
    if not observations:
        return 0, None, [], "no_supporting_observations"

    track_ids = {o.track_id for o in observations if o.track_id is not None}
    confidences = [o.confidence for o in observations if o.confidence is not None]

    if track_ids:
        # Reliable tracking available -> distinct tracked instances.
        return len(track_ids), _mean(confidences), [], "distinct_track_ids"

    # No tracking IDs (current ShelfDetector) -> max simultaneous per frame.
    by_frame: dict = {}
    for o in observations:
        frame_key = (o.source, o.frame_number)
        by_frame.setdefault(frame_key, []).append(o)
    per_frame_counts = [frame_instance_count(obs) for obs in by_frame.values()]
    observed = max(per_frame_counts) if per_frame_counts else 0
    return observed, _mean(confidences), per_frame_counts, "max_simultaneous_per_frame"


def mean_confidence(values: Sequence[float]) -> Optional[float]:
    return _mean(list(values))


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 4)
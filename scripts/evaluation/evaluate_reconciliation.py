#!/usr/bin/env python3
"""Reconciliation evaluation against ground-truth JSON.

Usage:
    python scripts/evaluation/evaluate_reconciliation.py \
        --ground-truth path/to/gt.json \
        --store-id <uuid>

Ground-truth format (JSON) — a list of expected counts:
    [
      {
        "product_id": "<uuid>",
        "camera_id": "<uuid or null>",
        "expected_quantity": 5,
        "window_start": "2026-01-01T00:00:00Z",
        "window_end":   "2026-01-01T08:00:00Z"
      }
    ]

Metrics (computed only when ground truth is available):
    - match accuracy  (observed == expected)
    - false shortage rate (observed < expected)
    - false surplus rate  (observed > expected)

Runs the existing ReconciliationService counting logic over the persisted
observation data in the connected database. Requires --store-id because the
service reconciles per store.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconciliation evaluation against ground-truth counts."
    )
    parser.add_argument(
        "--ground-truth", required=True, type=Path, help="path to GT JSON",
    )
    parser.add_argument(
        "--store-id", required=True, help="store UUID to reconcile (service scope)",
    )
    parser.add_argument(
        "--min-confidence", type=float, default=0.5,
        help="minimum observation confidence (default 0.5)",
    )
    args = parser.parse_args(argv)

    if not args.ground_truth.exists():
        print(f"[error] ground-truth not found: {args.ground_truth}", file=sys.stderr)
        return 2

    try:
        with open(args.ground_truth, "r", encoding="utf-8") as fh:
            gt = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[error] could not read ground truth: {exc}", file=sys.stderr)
        return 2

    if not isinstance(gt, list) or len(gt) == 0:
        print("GROUND TRUTH UNAVAILABLE")
        print("  Ground truth contains no entries; skipping evaluation (exit 0).")
        return 0

    # Normalise GT entries; validate each.
    entries = []
    malformed = 0
    for item in gt:
        product_id = item.get("product_id")
        expected = item.get("expected_quantity")
        start = _parse_iso(item.get("window_start"))
        end = _parse_iso(item.get("window_end"))
        if not product_id or expected is None or start is None or end is None:
            malformed += 1
            continue
        entries.append(
            {
                "product_id": str(product_id),
                "camera_id": str(item["camera_id"]) if item.get("camera_id") else None,
                "expected_quantity": int(expected),
                "window_start": start,
                "window_end": end,
            }
        )
    if not entries:
        print("GROUND TRUTH UNAVAILABLE")
        print(f"  No valid entries in ground truth ({malformed} malformed); exit 0.")
        return 0
    if malformed:
        print(f"[warn] {malformed} malformed GT entries skipped", file=sys.stderr)

    # Requires a database-backed service.
    try:
        from sqlalchemy.orm import Session
        from app.db.session import get_session
        from app.services.reconciliation.reconciliation_service import ReconciliationService
    except ImportError as exc:
        print(f"[error] missing dependency: {exc}", file=sys.stderr)
        print("  Is the backend venv active? Install sqlalchemy / run a DB first.")
        return 1

    session: Session = get_session()
    service = ReconciliationService(session)

    match = 0
    shortage = 0
    surplus = 0
    skipped = 0
    total_expected = 0
    total_observed = 0
    print(f"[info] reconciling {len(entries)} ground-truth entries...")
    try:
        for e in entries:
            try:
                result = service.reconcile_product(
                    store_id=args.store_id,
                    product_id=e["product_id"],
                    camera_id=e["camera_id"],
                    start=e["window_start"],
                    end=e["window_end"],
                    min_confidence=args.min_confidence,
                )
            except Exception as exc:
                print(f"[warn] reconcile failed for {e['product_id']}: {exc}", file=sys.stderr)
                skipped += 1
                continue

            observed = getattr(result, "ai_observed_quantity", None)
            if observed is None:
                skipped += 1
                continue
            total_expected += e["expected_quantity"]
            total_observed += observed
            if observed == e["expected_quantity"]:
                match += 1
            elif observed < e["expected_quantity"]:
                shortage += 1
            else:
                surplus += 1
    finally:
        session.close()

    n = len(entries) - skipped
    print("\n===== RECONCILIATION EVALUATION =====")
    print(f"  entries evaluated   : {n}")
    print(f"  entries skipped     : {skipped}")
    print(f"  match               : {match}"
          + (f" ({match/n:.4f})" if n else ""))
    print(f"  false shortage      : {shortage}"
          + (f" ({shortage/n:.4f})" if n else ""))
    print(f"  false surplus       : {surplus}"
          + (f" ({surplus/n:.4f})" if n else ""))
    print(f"  total expected units: {total_expected}")
    print(f"  total observed units: {total_observed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

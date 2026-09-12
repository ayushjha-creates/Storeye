#!/usr/bin/env python3
"""OCR + ExpiryParser dataset evaluation.

Wraps the existing backend/scripts/ocr_eval auditing and evaluation logic.
When the dataset has verified image<->ground-truth pairs, runs the existing
OCR pipeline (OCRService) + ExpiryParser on them and reports field-level
extraction accuracy for: expiry_date, manufacturing_date, batch_number, mrp.

Usage:
    python scripts/evaluation/evaluate_ocr.py \
        --dataset path/to/dataset \
        [--max-samples N]
    # dataset dir must contain images/ and ground_truth.csv

With zero verified pairs the dataset is still audited and the audit summary is
printed, then the script exits cleanly (no OCR inference is run).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow importing app.* (backend) and scripts.ocr_eval.* (the existing logic).
BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

# Ground-truth expiry date formats (ISO-like). CSV holds raw expiry_text.
_GT_FIELDS = ("expiry_date", "manufacturing_date", "batch_number", "mrp")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="OCR + ExpiryParser evaluation with field-level accuracy."
    )
    parser.add_argument(
        "--dataset", required=True, type=Path, help="dataset dir containing images/ and ground_truth.csv"
    )
    parser.add_argument(
        "--max-samples", type=int, default=None, help="cap number of samples evaluated"
    )
    args = parser.parse_args(argv)

    images_dir = args.dataset / "images"
    csv_path = args.dataset / "ground_truth.csv"

    if not csv_path.exists():
        print(f"[error] ground_truth.csv not found: {csv_path}", file=sys.stderr)
        return 2
    if not images_dir.is_dir():
        print(f"[error] images dir not found: {images_dir}", file=sys.stderr)
        return 2

    # Wrap the existing audit logic.
    try:
        from scripts.ocr_eval.audit import audit_dataset, summarize as audit_summary
        from scripts.ocr_eval.evaluate import _parse_gt_date, _crop
    except ImportError as exc:
        print(f"[error] could not import ocr_eval: {exc}", file=sys.stderr)
        return 1

    print("[info] auditing dataset (read-only)...")
    audit = audit_dataset(csv_path, images_dir)
    print(audit_summary(audit))

    if audit.matched_pairs == 0:
        print()
        print("0 verified pairs; no OCR inference run.")
        print("AUDIT COMPLETE (no data to evaluate; exit 0).")
        return 0

    # Verified pairs exist -> run OCR + parser for field-level accuracy.
    try:
        import cv2
        import csv as _csv
        from app.services.vision.ocr import OCRService
        from app.services.product.expiry_parser import ExpiryParser
    except ImportError as exc:
        print(f"[error] missing dependency: {exc}", file=sys.stderr)
        print("  Is the backend venv active? Install paddleocr first.")
        return 1

    print("\n[info] initialising OCR + ExpiryParser...")
    try:
        ocr = OCRService()
    except Exception as exc:
        print(f"[error] failed to initialise OCR: {exc}", file=sys.stderr)
        return 1
    parser = ExpiryParser()

    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))

    # Accumulate per-field correctness across samples.
    field_correct = {f: 0 for f in _GT_FIELDS}
    field_present_gt = {f: 0 for f in _GT_FIELDS}
    evaluated = 0

    def _field_predicted(meta, field):
        if field == "expiry_date":
            return meta.expiry_date.isoformat() if meta.expiry_date else None
        if field == "manufacturing_date":
            return meta.manufacturing_date.isoformat() if meta.manufacturing_date else None
        if field == "batch_number":
            return meta.batch_number
        if field == "mrp":
            return str(meta.mrp) if meta.mrp is not None else None
        return None

    def _gt_field_value(row, field):
        if field == "expiry_date":
            return _parse_gt_date(row.get("expiry_text") or "")
        if field in ("manufacturing_date", "batch_number", "mrp"):
            raw = (row.get(field) or "").strip()
            if not raw:
                return None
            if field == "manufacturing_date":
                return _parse_gt_date(raw)
            if field == "batch_number":
                return raw
            if field == "mrp":
                return raw
        return None

    print(f"[info] evaluating {len(audit.verified_pair_filenames)} verified image(s)...")
    for filename in audit.verified_pair_filenames:
        img_path = images_dir / filename
        if not img_path.exists():
            continue
        image = cv2.imread(str(img_path))
        if image is None:
            continue
        for row_idx in audit.csv_rows_per_image.get(filename, []):
            if args.max_samples is not None and evaluated >= args.max_samples:
                break
            row = rows[row_idx]
            crop = _crop(image, row)
            try:
                result = ocr.extract_text(crop)
                joined = " ".join(result.texts()).strip()
                meta = parser.parse(joined)
            except Exception as exc:
                print(f"[warn] OCR/parse failed {filename} row {row_idx}: {exc}", file=sys.stderr)
                continue

            evaluated += 1
            for field in _GT_FIELDS:
                gt_val = _gt_field_value(row, field)
                pred_val = _field_predicted(meta, field)
                if gt_val is None:
                    # No ground truth for this field -> do not score it.
                    continue
                field_present_gt[field] += 1
                if pred_val is not None and str(pred_val) == str(gt_val):
                    field_correct[field] += 1

    print("\n===== OCR + EXPIRYPARSER EVALUATION =====")
    print(f"  verified matched pairs  : {audit.matched_pairs}")
    print(f"  evaluated samples       : {evaluated}")
    print("\n  field-level accuracy (on samples where GT present):")
    for field in _GT_FIELDS:
        n = field_present_gt[field]
        if n:
            acc = field_correct[field] / n
            print(
                f"    {field:>22}: {field_correct[field]}/{n} "
                f"= {acc:.4f}"
            )
        else:
            print(f"    {field:>22}: n/a (no GT values present)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

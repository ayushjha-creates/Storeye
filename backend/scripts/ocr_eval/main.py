"""CLI entry point for OCR + ExpiryParser dataset evaluation.

Usage (from the backend/ directory, inside the Storeye venv):

    python -m scripts.ocr_eval.main \
        [--dataset /abs/path/to/data/datasets/ocr] \
        [--run-ocr] [-v]

Behavior:
  1. Audits the dataset (read-only): CSV rows, image files, verified pairs,
     unpaired rows, unreferenced images. Writes audit_report.json.
  2. If --run-ocr is given, evaluates OCR + ExpiryParser on VERIFIED pairs
     only and writes evaluation_report.json. With zero verified pairs, no OCR
     inference is run and the report records evaluated_samples = 0.

Ground truth is never modified; images are never renamed; no model is
fine-tuned.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure `app` is importable when run as `python -m scripts.ocr_eval.main`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ocr_eval.audit import audit_dataset, summarize as audit_summary, write_report as write_audit
from scripts.ocr_eval.evaluate import run_evaluation, summarize as eval_summary, write_report as write_eval


def _default_dataset_dir() -> Path:
    from app.core.config import get_settings
    return get_settings().BASE_DIR.parent / "data" / "datasets" / "ocr"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OCR + ExpiryParser dataset evaluation")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_default_dataset_dir(),
        help="directory holding images/ and ground_truth.csv (default: project data/datasets/ocr)",
    )
    parser.add_argument(
        "--run-ocr",
        action="store_true",
        help="evaluate OCR + ExpiryParser on verified image/GT pairs",
    )
    parser.add_argument("--max-samples", type=int, default=None,
                        help="cap the number of samples evaluated (diagnostic)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    images_dir = args.dataset / "images"
    csv_path = args.dataset / "ground_truth.csv"

    if not csv_path.exists():
        print(f"[error] ground_truth.csv not found: {csv_path}", file=sys.stderr)
        return 2
    if not images_dir.is_dir():
        print(f"[error] images dir not found: {images_dir}", file=sys.stderr)
        return 2

    # 1) Audit
    audit = audit_dataset(csv_path, images_dir)
    audit_out = args.dataset / "audit_report.json"
    write_audit(audit, audit_out)
    print(audit_summary(audit))
    print(f"  audit report written : {audit_out}")

    # 2) Evaluation (only if requested; only on verified pairs)
    if args.run_ocr:
        report = run_evaluation(
            audit,
            csv_path=csv_path,
            images_dir=images_dir,
            max_samples=args.max_samples,
            verbose=args.verbose,
        )
        eval_out = args.dataset / "evaluation_report.json"
        write_eval(report, eval_out)
        print()
        print(eval_summary(report))
        print(f"  evaluation report written : {eval_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""OCR + ExpiryParser evaluation over VERIFIED image<->ground-truth pairs.

Runs the existing PaddleOCR pipeline (OCRService) and the existing expiry
parser (ExpiryParser) on every *verified* pair, compares the predicted expiry
date against the ground-truth expiry_text, and writes a JSON report.

Pairs are only those established by exact filename match in the audit. Images
with no verified ground-truth row are NEVER evaluated. With zero verified pairs
(an empty/unpaired dataset), NO OCR inference runs and the report records
evaluated_pairs = 0 — no assumptions are made about unpaired images.

Ground-truth data is read-only. No model is fine-tuned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from .audit import DatasetAudit

# Ground-truth date formats attempted (in this order) on expiry_text.
_GT_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d-%b-%Y",
    "%d %b %Y",
)

CROP_PADDING = 4  # px around the annotated bbox before OCR


@dataclass
class SampleResult:
    image_name: str
    csv_row: int
    ground_truth_text: Optional[str]
    ground_truth_date: Optional[str]  # ISO string or None if unparsed GT
    predicted_date: Optional[str]       # ISO string or None
    correct: bool
    ocr_conf_mean: Optional[float]
    ocr_text_joined: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvaluationReport:
    dataset_csv: str
    images_dir: str
    verified_pairs: int = 0
    evaluated_samples: int = 0
    correct: int = 0
    wrong: int = 0
    unreported: int = 0
    accuracy: Optional[float] = None  # correct / evaluated_samples
    samples: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_gt_date(text: str) -> Optional[date]:
    from datetime import datetime
    if not text:
        return None
    candidate = text.strip()
    for fmt in _GT_DATE_FORMATS:
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    # Month-name variants like "13-Jan-2026" handled by %d-%b-%Y; also try
    # "January 5 2026" style explicitly.
    for fmt in ("%d-%B-%Y", "%B %d %Y", "%d %B %Y"):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


def _crop(image: object, row: dict) -> object:
    """Crop a copy of the image to the annotated bbox (with padding).

    Falls back to the whole image when bbox fields are missing/invalid, so OCR
    still has a chance when the annotation is incomplete. Never mutates input.
    """
    import cv2
    try:
        x = int(row["bbox_x"]); y = int(row["bbox_y"])
        w = int(row["bbox_width"]); h = int(row["bbox_height"])
        H, W = image.shape[:2]
        x1 = max(0, x - CROP_PADDING); y1 = max(0, y - CROP_PADDING)
        x2 = min(W, x + w + CROP_PADDING); y2 = min(H, y + h + CROP_PADDING)
        if x2 > x1 and y2 > y1:
            return image[y1:y2, x1:x2]
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    return image


def run_evaluation(
    audit: DatasetAudit,
    *,
    csv_path: Path,
    images_dir: Path,
    max_samples: Optional[int] = None,
    verbose: bool = False,
) -> EvaluationReport:
    """Run OCR+parser over verified pairs and return an EvaluationReport."""
    report = EvaluationReport(
        dataset_csv=str(csv_path),
        images_dir=str(images_dir),
        verified_pairs=audit.matched_pairs,
    )

    if audit.matched_pairs == 0:
        # Nothing verified to evaluate. Do not guess; do not run OCR.
        return report

    import cv2

    # Read CSV rows once, keyed by row index.
    import csv as _csv
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))

    # Load OCR + parser lazily only now that we actually have pairs to run.
    from app.services.vision.ocr import OCRService
    from app.services.product.expiry_parser import ExpiryParser

    ocr = OCRService()
    parser = ExpiryParser()

    evaluated = 0
    for filename in audit.verified_pair_filenames:
        img_path = images_dir / filename
        if not img_path.exists():
            continue
        image = cv2.imread(str(img_path))
        if image is None:
            continue

        for row_idx in audit.csv_rows_per_image.get(filename, []):
            if max_samples is not None and evaluated >= max_samples:
                break
            row = rows[row_idx]
            gt_text = (row.get("expiry_text") or "").strip()
            gt_date = _parse_gt_date(gt_text)

            crop = _crop(image, row)
            result = ocr.extract_text(crop)
            texts = result.texts()
            joined = " ".join(texts).strip()

            # The parser is OCR-independent and accepts a raw string; feed it
            # the joined raw OCR text so we evaluate the full pipeline faithful
            # to what OCR actually read.
            parsed = parser.parse(joined)

            predicted = parsed.expiry_date
            correct = bool(predicted and gt_date and predicted == gt_date)

            confs = [it.confidence for it in result.items]
            mean_conf = (sum(confs) / len(confs)) if confs else None

            sample = SampleResult(
                image_name=filename,
                csv_row=row_idx,
                ground_truth_text=gt_text or None,
                ground_truth_date=gt_date.isoformat() if gt_date else None,
                predicted_date=predicted.isoformat() if predicted else None,
                correct=correct,
                ocr_conf_mean=round(mean_conf, 4) if mean_conf is not None else None,
                ocr_text_joined=joined,
            )
            report.samples.append(sample.to_dict())
            report.evaluated_samples += 1
            if correct:
                report.correct += 1
            else:
                report.wrong += 1

            if verbose:
                mark = "OK " if correct else "XX "
                print(
                    f"{mark} {filename} row {row_idx}: gt={gt_text!r} "
                    f"pred={predicted} (conf={mean_conf if mean_conf is not None else 'n/a'})"
                )

    if report.evaluated_samples:
        report.accuracy = round(report.correct / report.evaluated_samples, 4)

    return report


def write_report(report: EvaluationReport, out_path: Path) -> Path:
    out_path.write_text(
        json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    return out_path


def summarize(report: EvaluationReport) -> str:
    lines = [
        "OCR + ExpiryParser evaluation",
        f"  verified image/GT pairs : {report.verified_pairs}",
        f"  evaluated samples       : {report.evaluated_samples}",
        f"  correct                 : {report.correct}",
        f"  wrong                   : {report.wrong}",
        f"  accuracy                : {report.accuracy if report.accuracy is not None else 'n/a (nothing evaluable)'}",
    ]
    return "\n".join(lines)
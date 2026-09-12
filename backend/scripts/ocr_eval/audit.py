"""Dataset audit for data/datasets/ocr.

Deterministic, read-only accounting of the ground-truth CSV and the image
directory. It never renames files, never matches images to rows by index, and
never invents a correspondence. The ONLY verified key is an exact filename
collision between a CSV `image_name` and a file present in the images dir.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List


@dataclass
class DatasetAudit:
    csv_path: str
    images_dir: str

    total_csv_rows: int = 0
    distinct_image_names: int = 0
    total_image_files: int = 0
    matched_pairs: int = 0
    unpaired_csv_rows: int = 0
    unreferenced_image_files: int = 0

    # image_name -> list of CSV row indices (0-based) that reference it.
    csv_rows_per_image: Dict[str, List[int]] = field(default_factory=dict)
    # image filename -> True for files actually present on disk.
    present_files: Dict[str, bool] = field(default_factory=dict)
    # image filenames present on disk AND referenced by the CSV (verified pairs).
    verified_pair_filenames: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _read_csv(path: Path) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def audit_dataset(
    csv_path: Path,
    images_dir: Path,
) -> DatasetAudit:
    rows = _read_csv(csv_path)
    present = sorted(
        p.name for p in images_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    )

    csv_names = [r.get("image_name", "").strip() for r in rows]
    present_set = set(present)

    # Map each CSV image_name to the set of row indices referencing it.
    rows_per_image: Dict[str, List[int]] = {}
    for idx, name in enumerate(csv_names):
        if not name:
            continue
        rows_per_image.setdefault(name, []).append(idx)

    # Verified pairs = image_name that is BOTH referenced by the CSV and present
    # on disk (exact filename match). No other key is trusted.
    verified = sorted(set(rows_per_image.keys()) & present_set)

    total_rows = len(rows)
    distinct_names = len(rows_per_image)
    total_images = len(present)
    matched = len(verified)

    return DatasetAudit(
        csv_path=str(csv_path),
        images_dir=str(images_dir),
        total_csv_rows=total_rows,
        distinct_image_names=distinct_names,
        total_image_files=total_images,
        matched_pairs=matched,
        unpaired_csv_rows=total_rows - matched,
        unreferenced_image_files=total_images - matched,
        csv_rows_per_image=rows_per_image,
        present_files={name: (name in present_set) for name in sorted(rows_per_image)},
        verified_pair_filenames=verified,
    )


def write_report(audit: DatasetAudit, out_path: Path) -> Path:
    out_path.write_text(
        json.dumps(audit.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    return out_path


def summarize(audit: DatasetAudit) -> str:
    lines = [
        "OCR dataset audit",
        f"  CSV ground-truth path    : {audit.csv_path}",
        f"  images dir               : {audit.images_dir}",
        f"  total CSV rows           : {audit.total_csv_rows}",
        f"  distinct image names     : {audit.distinct_image_names}",
        f"  total image files        : {audit.total_image_files}",
        f"  verified matched pairs   : {audit.matched_pairs}",
        f"  unpaired CSV rows        : {audit.unpaired_csv_rows}",
        f"  unreferenced image files : {audit.unreferenced_image_files}",
    ]
    return "\n".join(lines)
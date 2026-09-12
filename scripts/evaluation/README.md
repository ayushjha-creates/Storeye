# Storeye Evaluation Framework

Scripts to evaluate the Storeye CV + reconciliation components against
ground-truth data. All scripts reuse the existing backend services
(`app.services.vision.*`, `app.services.reconciliation.*`) — **no new ML
dependencies** are added.

## Requirements

- The Storeye **backend** environment must be active (Ultralytics for the
  detectors/tracker, PaddleOCR for OCR, SQLAlchemy for reconciliation).
- Each script inserts the `backend/` directory onto `sys.path` and imports
  the existing services directly.
- A running database is required **only** for the reconciliation script.

## Exit codes

| Code | Meaning                                        |
|------|------------------------------------------------|
| 0    | Success (also when ground truth is unavailable) |
| 1    | Error (missing dependency, model load failure)  |
| 2    | Missing input data (paths/GT absent)            |

## Scripts

### 1. Person detection & tracking — `evaluate_people.py`

```bash
python scripts/evaluation/evaluate_people.py \
    --video /path/to/video.mp4 \
    --ground-truth /path/to/gt.json \
    --conf 0.25
```

Ground-truth JSON:

```json
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
```

- Detection **precision / recall** via greedy IoU matching (`IoU >= 0.5`).
- Tracking **IDF1 components** and **ID switch count** when GT provides
  `track_id`. If GT has no `track_id`, tracking metrics are reported as
  unavailable.
- When GT has no frames, prints `GROUND TRUTH UNAVAILABLE` and exits 0.

### 2. Shelf detection — `evaluate_shelves.py`

```bash
python scripts/evaluation/evaluate_shelves.py \
    --images-dir /path/to/images \
    --ground-truth /path/to/gt.json \
    --conf 0.25
```

Ground-truth JSON:

```json
{
  "images": {
    "shelf_01.jpg": [
      {"bbox": [x1, y1, x2, y2], "class_name": "Complan", "class_id": 0}
    ]
  }
}
```

- **Per-class precision / recall** and overall precision / recall.
- **mAP** (mean per-class recall).
- **Confidence** distribution of detections.
- When GT has no images, prints `GROUND TRUTH UNAVAILABLE` and exits 0.

### 3. OCR + ExpiryParser — `evaluate_ocr.py`

```bash
python scripts/evaluation/evaluate_ocr.py \
    --dataset /path/to/dataset \
    [--max-samples N]
```

The dataset dir must contain `images/` and `ground_truth.csv`. This wraps the
existing `backend/scripts/ocr_eval` audit logic and, when verified
image<->GT pairs exist, runs OCR (`OCRService`) + `ExpiryParser` and reports
field-level accuracy for:

- `expiry_date`
- `manufacturing_date`
- `batch_number`
- `mrp`

With **zero verified pairs**, the audit summary is printed and the script
exits 0 (no OCR inference is run).

### 4. Reconciliation — `evaluate_reconciliation.py`

```bash
python scripts/evaluation/evaluate_reconciliation.py \
    --ground-truth /path/to/gt.json \
    --store-id <uuid> \
    [--min-confidence 0.5]
```

Ground-truth JSON (a list):

```json
[
  {
    "product_id": "<uuid>",
    "camera_id": "<uuid or null>",
    "expected_quantity": 5,
    "window_start": "2026-01-01T00:00:00Z",
    "window_end": "2026-01-01T08:00:00Z"
  }
]
```

Runs the existing `ReconciliationService` over persisted observations in the
connected database and reports:

- **match accuracy** (observed == expected)
- **false shortage rate** (observed < expected)
- **false surplus rate** (observed > expected)

`--store-id` is required because the service reconciles per store. When GT is
empty/unusable, prints `GROUND TRUTH UNAVAILABLE` and exits 0.

## Notes

- Scripts **never fabricate metrics**. When ground truth is missing or a value
  cannot be computed, they report `n/a` rather than guessing.
- Existing backend code is **not modified**; these scripts only import and call
  the current services.

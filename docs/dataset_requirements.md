# Storeye Dataset Requirements

Requirements for the datasets needed to validate Storeye across Milestones 0–10
and to support future model development and evaluation.

This document scopes **what** data must be collected, **how much**, in **what
format**, and **in what order**. Actual collected datasets live in
`data/datasets/`; only small deterministic fixtures belong in `data/tests/`.

---

## 1. Overview

Storeye relies on computer vision observations (people, shelves, OCR labels)
that are fed into a reconciliation-first decision pipeline. The four datasets
below correspond to the four CV capabilities the product depends on:

| Dataset | Capability | Milestone(s) | Current state |
|---------|-----------|--------------|---------------|
| Person detection / tracking | Footfall, queue, ROI counting | 1, 2, 5 | 22 raw videos, unannotated |
| Shelf / product detection | Stock-out, gap detection | 3, 4 | 39 raw photos, unannotated; pretrained 55-class model |
| OCR / expiry label | Expiry (FEFO), batch, MRP | 9 | 60 raw images; 0 verified pairs |
| Reconciliation | Truth vs. ledger, stock-out classification | 3, 7 | None |

These datasets are used for:

- **Validation** — proving each milestone works on real-world (not synthetic)
  data.
- **Evaluation** — measuring precision/recall of detectors, trackers, and the
  OCR+parser pipeline.
- **Future model improvement** — fine-tuning or distilling the current
  pretrained models.

---

## 2. Person Detection / Tracking Dataset

### Purpose

Validate person detection (COCO class 0), tracking, and ROI-based footfall /
queue metrics at the edge.

### Requirements

| Aspect | Requirement |
|--------|-------------|
| **Number of videos** | 5–10 short clips, 5–30 seconds each |
| **Scenarios** | Entrance, shelf browsing, queue, checkout, exit |
| **Lighting** | Indoor artificial light — typical Indian retail store |
| **Occlusion** | Partial occlusion acceptable/expected — people behind shelves, counters |
| **Crowd density** | 1–5 people per frame |
| **Annotations per frame** | Person bounding boxes `[x1,y1,x2,y2]`; optional `track_id` for multi-frame clips |
| **Format** | JSON with frame-level annotations |

### Notes on source videos

`data/datasets/people/videos/` currently holds 22 WhatsApp store-interaction
videos (~116 MB). These are the raw source material but are **ungrounded**
(counter/people scenes, no clean frontal infrastructure). Clips should be
selected/trimmed to the five scenarios above before annotation.

### JSON format (example)

```json
{
  "video_name": "entrance_1.mp4",
  "fps": 25,
  "width": 1280,
  "height": 720,
  "frames": [
    {
      "frame_id": 0,
      "timestamp_ms": 0,
      "persons": [
        {"bbox": [120, 60, 300, 420], "track_id": 1}
      ]
    },
    {
      "frame_id": 25,
      "timestamp_ms": 1000,
      "persons": [
        {"bbox": [130, 70, 310, 430], "track_id": 1},
        {"bbox": [600, 90, 760, 460], "track_id": 2}
      ]
    }
  ]
}
```

---

## 3. Shelf / Product Detection Dataset

### Purpose

Validate shelf/product detection against the pretrained fine-tuned model and
enable future fine-tuning / evaluation for stock-out and gap detection.

### Requirements

| Aspect | Requirement |
|--------|-------------|
| **Number of images** | 20–50 shelf photos |
| **Product classes** | Start with 5–10 common Indian FMCG products (Complan, Glucon-D, Nutralite, etc.) |
| **Shelf conditions** | Full shelves, partially stocked, empty sections |
| **Angles** | Mostly frontal — within 30 degrees of perpendicular to the camera |
| **Lighting** | Indoor artificial |
| **Annotations per image** | Bounding boxes `[x1,y1,x2,y2]`, `class_name`, `class_id` |
| **Format** | JSON with image-level annotations |

### Existing 55-class model

`models/shelf/shelf_model.pt` is a fine-tuned Ultralytics YOLO
(`task='detect'`, `imgsz=640`) with **55 Indian FMCG product classes**:

Complan (various), Everyuth Naturals, Glucon-D, Nutralite (mayo, ghee,
spread), Nycil, Sugar Free (Gold/GRN/Natura), Sugarlite.

New datasets must either:

- **Match** these class names/IDs where products overlap (so annotations
  evaluate directly against the existing model), or
- **Extend** them for new classes, with a documented class-mapping so old and
  new labels are unambiguous.

`class_name` and `class_id` must be kept consistent with the model's `names`
dictionary.

### JSON format (example)

```json
{
  "image_name": "shelf_full_1.jpg",
  "width": 1314,
  "height": 650,
  "objects": [
    {"bbox": [45, 120, 210, 320], "class_id": 0,  "class_name": "Complan"},
    {"bbox": [260, 130, 430, 330], "class_id": 2,  "class_name": "Glucon-D"},
    {"bbox": [500, 110, 680, 300], "class_id": 3,  "class_name": "Nutralite"}
  ]
}
```

### Current shelf captures

`data/datasets/shelves/images/` holds 39 shelf photos + 3 shelf videos (~5.5 MB,
captured 2026-09-02/03) showing store shelves. **No annotations exist yet.**
These are the natural starting point for curation, but each image must be
individually verified for class/bbox correctness before inclusion.

---

## 4. OCR / Expiry Label Dataset

### Purpose

Validate the OCR + expiry parsing pipeline end-to-end: text-region detection,
raw text extraction, and parsing of expiry / manufacturing date / batch / MRP.

### Requirements

| Aspect | Requirement |
|--------|-------------|
| **Number of images** | 100–200 product label photos |
| **Fields to capture** | `EXP` (expiry), `MFG`/`MFD` (manufacturing date), `BATCH`/`LOT`, `MRP` |
| **Date formats** | DD/MM/YYYY, MM/YYYY, DD-MM-YYYY, various separators |
| **Packaging types** | Printed labels, embossed, sticker, handwritten |
| **Variations** | Different fonts, sizes, orientations, partial occlusion |
| **Lighting** | Indoor artificial; some glare acceptable |
| **Blur / angle** | Slight blur and angle variation acceptable (real-world conditions) |
| **Annotations per image** | `bbox` `[x1,y1,x2,y2]` per text region, `expiry_text` (raw), `expiry_date` (parsed ISO date), `manufacturing_date`, `batch_number`, `mrp` |
| **Format** | CSV with the columns below |

### CSV columns

```
image_name, bbox_x, bbox_y, bbox_width, bbox_height, expiry_text,
expiry_date, manufacturing_date, batch_number, mrp
```

### Current dataset problem

`data/datasets/ocr/` holds 60 images but its `ground_truth.csv` is a 1000-row
file whose rows reference `IMG_0000.jpg` … `IMG_0999.jpg` while the actual
images are named `1.jpeg`, `2.jfif`, `12.webp`, etc.

**Result: 0 verified matched pairs** — `audit_report.json` and
`evaluation_report.json` both confirm no image↔row correspondence could be
established. No files were renamed or fabricated to force a match.

The new dataset must **fix the pairing**: every CSV row's `image_name` must
point to a real file in the dataset, and every annotated row must be verified
against the actual image content.

### CSV format (example)

```csv
image_name,bbox_x,bbox_y,bbox_width,bbox_height,expiry_text,expiry_date,manufacturing_date,batch_number,mrp
IMG_0001.jpg,120,340,310,60,"EXP: 12/2027",2027-12-31,,B2415,269.0
IMG_0002.jpg,90,410,270,55,"EXP 31/12/2026",2026-12-31,2025-01-15,,215.0
IMG_0003.jpg,150,220,280,50,"MFG 04/2025 BATCH L901",,2025-04-01,L901,
```

`expiry_date` (and `manufacturing_date`, where present) is the **parsed ISO
date** (YYYY-MM-DD). When only month+year is known, use the last day of that
month (e.g. `EXP: 12/2027` → `2027-12-31`). Empty cells mean the field is not
present or not legible — never guess.

---

## 5. Reconciliation Dataset

### Purpose

Validate the reconciliation engine: combining visual observations with ground
truth product counts to classify
`PHANTOM_INVENTORY / REPLENISHMENT_REQUIRED / OUT_OF_STOCK /
PREDICTED_STOCK_OUT / NO_ACTION / NEEDS_MORE_EVIDENCE`.

### Requirements

| Aspect | Requirement |
|--------|-------------|
| **Number of scenarios** | 5–10 product/camera combinations |
| **Ground truth** | Actual product count per camera per time window |
| **Annotations** | `product_id`, `camera_id`, `actual_quantity`, `observation_window` |
| **Format** | JSON |

### Difficulty

This is the **hardest dataset to create**. It requires a human physically
counting products on the shelf during each observation window, then correlating
that count with the camera view, the planogram, and the ledger. It depends on
the person, shelf, and (ideally) OCR datasets being usable first.

### JSON format (example)

```json
{
  "scenarios": [
    {
      "scenario_id": "s1",
      "product_id": "P-COMPLAN-250",
      "camera_id": "CAM-SHELF-A",
      "observation_window": {
        "start": "2026-09-04T10:00:00+05:30",
        "end":   "2026-09-04T10:30:00+05:30"
      },
      "actual_quantity": 18,
      "ledger_quantity": 20,
      "notes": "2 units removed by customer; no restock"
    }
  ]
}
```

`ledger_quantity` is optional context; `actual_quantity` is the required ground
truth observed by a person.

---

## 6. Priority Order

Create the datasets in this order, because each one is a prerequisite
or reduces the risk/effort of the next:

| Order | Dataset | Impact | Feasibility | Rationale |
|-------|---------|--------|-------------|-----------|
| 1 | **OCR / Expiry labels** | High | High | Current dataset is broken (0 verified pairs); highest immediate value for Milestone 9; labels are cheap to photograph (one product at a time) |
| 2 | **Shelf / product detection** | Medium | Moderate | 39 photos already collected; needs clean shelf shots + verified annotations; directly powers stock-out/gap detection |
| 3 | **Person detection / tracking** | Lower immediate | Higher | Already works with pretrained weights (COCO class 0); the MVP only needs plumbing validation, and raw videos already exist |
| 4 | **Reconciliation** | Highest effort | Depends on others | Needs usable shelf/person data + manual counting; build only after the visual datasets are trustworthy |

---

## 7. Data Quality Guidelines

These rules apply to **all four datasets** without exception:

1. **No fabricated annotations.** Never invent a bounding box, class, text, or
   count that is not actually present in the source image/video.

2. **No index-based guessing of image↔annotation correspondence.** Never assume
   row *N* of a CSV matches file *N* of a list. Correspondence must be
   established explicitly by filename and verified against the actual file.

3. **Every annotation must be verified against the actual image.** Each label
   is checked visually against the pixels/audio it refers to before it is
   accepted into the dataset.

4. **Be conservative.** Only annotate what is clearly visible. If a product is
   half-hidden, a date partially legible, or a person only a body part, either
   annotate the visible portion with a note or skip it. Do not extrapolate.

5. **Document ambiguous cases.** Wherever an interpretation was required
   (e.g. a cut-off date, an unknown batch, a glare-obscured MRP), record it in
   the dataset notes/`README` or inline so evaluators and future maintainers
   can understand the decision.

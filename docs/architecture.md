# EdgeRetail-IQ — Architecture & Roadmap

## Layered Architecture

Six logical layers, each mapped to the milestone that delivers it.

### L1 — CAPTURE
USB webcam / RTSP / video file through a `CameraSource` abstraction.
Configurable frame skipping. Shelf checks run at low frequency (~10–30s),
not full FPS.

### L2 — EDGE INFERENCE
Person detection (COCO class 0), shelf/product detection, anonymous tracking.
Pretrained weights only — no custom training. Models configurable.

### L3 — TEMPORAL & BUSINESS LOGIC
ROI polygons (entrance, queue, shelf, billing tray, general). Temporal
persistence filter with a state machine:

`NORMAL → PENDING_GAP → BLOCKED → VERIFIED_GAP → RECONCILING → ACTION_REQUIRED → RESOLVED`

A single observed gap never fires an alert; obstruction suppresses it.

### L4 — RECONCILIATION MIDDLEWARE (most important)
Dedicated reconciliation engine. Combines: visual event, SKU, planogram,
inventory ledger, backroom stock, POS/WMS. Classifies:
`PHANTOM_INVENTORY / REPLENISHMENT_REQUIRED / OUT_OF_STOCK / PREDICTED_STOCK_OUT / NO_ACTION / NEEDS_MORE_EVIDENCE`.

Visual empty shelf ≠ stock-out. Ledger + backroom determine truth.

### L5 — LOCAL DATA + SYNC
PostgreSQL (18) is the local source of truth, owned by Alembic migrations and
served to the (also local) web frontend through FastAPI. UUID primary keys,
UTC timestamps. No cloud sync/supabase — the earlier SQLite plan was superseded
(see `docs/database.md`).

### L6 — PRESENTATION
Manager dashboard, associate PWA, billing UI, analytics, inventory
workbench, digital twin (store map), evidence, copilot.

## Pipeline

```
Camera → Edge Inference → Temporal Filtering → Reconciliation → Business Impact →
Priority (Urgency/Revenue/Customer) → Recommendation → Human Confirmation →
Staff Action → Outcome → Effectiveness → Local Learning
```

## Product Thesis

EdgeRetail-IQ is NOT primarily computer vision. CV provides observations.
The differentiated value is the middleware: reconciliation-first decision
pipeline over offline-first, privacy-preserving edge infrastructure.

## Milestones

| Milestone | Focus | Status |
|-----------|-------|--------|
| 0 | Foundation: backend, frontend, SQLite, health, tests | ✅ |
| 1 | Camera + YOLO + tracking + ROI | pending |
| 2 | SQLite syncable entities + event system | ✅ (superseded: PostgreSQL) |
| 3 | Temporal filter + reconciliation (core) | pending |
| 4 | Dashboard + inventory workbench + Excel | pending |
| 5 | Queue + shopper analytics | pending |
| 6 | Billing (vision, GST, UPI QR, WhatsApp) | pending |
| 7 | Predictive stock-out + priority + revenue-at-risk | pending |
| 8 | Effectiveness loop | pending |
| 9 | Procurement + FEFO + OCR | pending |
| 10 | Digital twin + explainability | pending |
| 11 | Copilot | pending |
| 12 | Web frontend: auth foundation, edge-first UI, offline-first | ✅ |
| 13 | Security + hardening | pending |
| 14 | Full offline integration + demo | pending |

## Confidence Model

Two distinct confidence values, never conflated:

- **CV detection confidence** — model's frame-level certainty
- **Business decision confidence** — reduced by stale ledger, conflicting
  inventory, short observation window, missing backroom data

Low business confidence routes back to reconciliation for more evidence.

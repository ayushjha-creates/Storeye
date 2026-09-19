# Milestone 15 — Product & Shelf Intelligence

**Date:** 2026-09-07
**Status:** ✅ Implemented and verified

---

## Summary

M13/M14 built the Edge AI observation pipeline (shelf/product YOLO → observations →
PostgreSQL → FastAPI → React). M15 turns that stream of real observations into honest,
useful **product** and **shelf** intelligence. Visible quantities and occupancy are
estimated from real detections, then compared **informationally** against recorded DB
inventory and planogram expectations. All values are explicitly AI-estimated;
inventory, batches, bills and sales are never auto-mutated. PostgreSQL is still the
single authoritative business database, and inference stays fully on-device.

## The M15 data flow

```
Shelf camera (offline, on device)
   │  ShelfDetector (55-class retail YOLO, local weights)
   ▼
PRODUCT events ─▶ ObservationWriter ─▶ observations (product_id from explicit mapping)
   │                                        details.class_name
   ▼                                        details.bbox_xyxy
Shared counting (count_visible) ◀────────┘
   ▼
ProductIntelligenceService  -----------▶ /api/intelligence/products   (visible vs recorded)
ShelfIntelligenceService   -----------▶ /api/intelligence/shelves     (occupancy + state)
…
MisplacementService          -----------▶ /api/intelligence/misplacements
AISummaryService             -----------▶ /api/intelligence/summary
```

## Hard rules honoured

- **AI → business boundary.** Intelligence services are read-only computations over
  observations + inventory + planogram data. They **never** auto-increment/decrement
  inventory, and never create movements, batches, bills or sales. Differences are
  surfaced as "Possible shortage / Possible surplus", region occupancy as
  "AI-estimated visible occupancy", and no detection ever becomes a "Confirmed
  shortage" or "Out of stock".
- **Explicit class→product mapping only.** `Product.ai_classes` (JSONB list of class
  names) is the only way an AI class becomes a product. Unmapped classes are
  "Unmapped AI class", surfaced but never guessed. The Edge `ObservationWriter` and the
  intelligence services use the **same deterministic mapping** (first product by SKU
  order wins per class).
- **Shared counting.** `count_visible` from `app/services/reconciliation/counting.py` —
  distinct track ids when available, else max-simultaneous-per-frame with IoU ≥ 0.5
  dedup for PRODUCT observations.
- **Camera-scoped.** Every intelligence row is (class, camera), never fused across
  cameras into one global stock number.
- **Terminology.** "Visible quantity", "AI-estimated visible occupancy", "Possible
  shortage/surplus/misplacement", "Unmapped AI class". "Actual stock"/"Out of stock"
  are never produced by AI.

## What was delivered

### Data layer
- Alembic migration `b7f3d11e4a59_add_product_ai_classes` (current head) adds
  `products.ai_classes` JSONB. `Product` model + create/update/read schemas include it.
- `test_migrations.py` `EXPECTED_HEAD` bumped to `b7f3d11e4a59`; upgrade/downgrade
  round-trip verified against `storeye_test`.

### Writer enrichment
- `ObservationWriter` now resolves the store's explicit class→product mapping once
  (`_load_class_to_product`) and stamps `product_id` on PRODUCT observations. Unmapped
  classes keep `product_id=None`. This is the only place the Edge runtime touches the
  data layer, and it still uses `ObservationService` only.

### Observation filter
- `GET /api/observations` and `GET /api/observations/summary` accept `class_name`
  (matches `details.class_name` via JSONB `astext`), so intelligence pages can show a
  class's raw detection history.

### Intelligence services (`backend/app/services/intelligence/`)
| Service | Output |
|---------|--------|
| `shelf_intelligence.py` | `parse_shelf_regions` (validated `{code, label?, bbox}` from `camera.config.shelf_regions`, deterministic order), per-region occupancy (`occupied_pct` included) with temporal smoothing (`occupancy_method` `raw`/`median_60s`), shelf states `UNKNOWN / EMPTY_VISIBLE / LOW_VISIBLE / NORMAL_VISIBLE` (LOW = half full or less, `LOW_OCCUPANCY_FRACTION=0.5`) plus `refill_recommended`, majority-shelf association, per-product expectations + misplacement flags. Consumed by the M16 alert layer (`SHELF_EMPTY` / `LOW_SHELF_OCCUPANCY` refill alerts). |
| `product_intelligence.py` | per (class, camera) rows: visible quantity (shared counting), mapped product + DB quantity, `comparison_status` `MATCH / POSSIBLE_SHORTAGE / POSSIBLE_SURPLUS / NO_INVENTORY / NOT_ASSESSED`, shelf association message |
| `misplacement.py` | `POSSIBLE_MISPLACEMENT` only for **mapped** products whose shelf has an active `PlanogramItem` expectation excluding them; unmapped classes / no expectation never flagged |
| `ai_summary.py` | 24 h digest: cameras (active/ai-running/regions configured), people, products (visible/mapped/unmapped/total quantity), shelves (states + possible misplacements), reconciliation counters |

### API (all read-only, router prefix `/api/intelligence`)
| Endpoint | Purpose |
|----------|---------|
| `GET /api/intelligence/products` | visible-vs-recorded per (class, camera) |
| `GET /api/intelligence/shelves` | region occupancy, state, visible products, misplacements |
| `GET /api/intelligence/summary` | dashboard digest |
| `GET /api/intelligence/misplacements` | misplacement-only list |

`store_id` guard required; invalid → 400.

### Frontend
- `types.ts` — M15 intelligence types + `Product.ai_classes?`.
- `lib/api/intelligence.ts` — typed clients + label maps for statuses/states.
- `ProductIntelligencePage` (`/product-intelligence`) — comparison table with status
  badges (Possible shortage/surplus, Unmapped AI class, No inventory, Not assessed) and
  a minimal **class→product mapping editor** (map an unmapped class via
  `PATCH /api/products/:id` `ai_classes`).
- `ShelfIntelligencePage` (`/shelf-intelligence`) — region cards (state badge,
  occupancy bar with `occupied_pct`, visible products, "possible misplaced" flags,
  honest "Unknown — no AI data").
- Routes + AppShell nav ("Product Intel" / "Shelf Intel"); Dashboard AI Intelligence
  card; per-camera product + shelf sections in `CameraDetail`.

## Verification (honest numbers)

### Backend
- Full suite (`python -m pytest tests/ -q`): **161 passed** (4 warnings).
- `test_intelligence.py` — **20 tests**: shared counting words, possible shortage /
  surplus / no-inventory / unmapped, camera scoping, `class_name` filter, occupancy &
  `occupied_pct`, shelf states, misplacement (mapped-world only), confidence floor,
  temporal window, no-mutation guard (inventory/batches/bills/sales all untouched),
  summary digest, regions parsing.
- Migration chain: `alembic upgrade head` → `b7f3d11e4a59`; downgrade/upgrade
  round-trip OK.
- **Known/accepted `alembic check` note:** `alembic check` reports "New upgrade
  operations detected" — a whole-model diff. This project never kept `Base.metadata`
  and the Alembic chain in lockstep (the chain is verified separately by
  `test_migrations.py`), so this is expected and not a regression.
- Real-model smokes (`pytest -m real_ai`): **2 passed** — person tracking on the demo
  video, and a new shelf-product smoke that runs the real ShelfDetector over
  `data/datasets/shelves/images` and requires a real detection.

### Frontend
- **62 tests pass** (17 files), `npx tsc -b` clean, **`npm run build` passes**.
- New tests: ProductIntelligencePage (comparison rendering, shortage + unmapped rows,
  mapping editor PATCHes `ai_classes`), ShelfIntelligencePage (occupancy %, state
  badges, misplaced flag, unknown/empty states).

## Edge-first / offline guarantees
Unchanged: inference is local (person YOLO11n + shelf 55-class weights), no cloud
inference, no internet required, PostgreSQL the single store. PaddleOCR first-run
download caveat from M14 still applies.

## Safety & scope boundaries (unchanged)
- AI observations are **informational only**; the intelligence layer is read-only and
  never auto-reconciles. Inventory reconciliation stays a human-reviewed, explicit
  action.
- No second database, no cloud sync, no auto-billing/bills, no auth implementation.

## Not built (explicitly out of scope for M15)
Cloud sync, WhatsApp/SMS alerts, auto-billing, planogram authoring UI
(read via existing `PlanogramItem`s, editing is not in this milestone), fleet /
multi-store, offline install packaging.

## Next
M16 per roadmap.
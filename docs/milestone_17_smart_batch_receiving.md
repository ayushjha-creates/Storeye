# Milestone 17 — Smart Batch Receiving + Close-Up OCR

**Date:** 2026-09-09
**Status:** ✅ Implemented and verified

---

## Summary

M6 introduced an OCR + ExpiryParser to read bill lines, and M13 plugged the same
OCR stack into the continuous CCTV pipeline as an opt-in experimental tap. Neither
was a way to get **batch-level stock data** into inventory reliably: reading a
printed `EXP:`/`MFG:`/`BATCH:`/`MRP:` label from a ceiling camera at distance is
not dependable, and no human-review gate existed.

M17 fixes the job the right way: a **close-up, shopkeeper-assisted intake** built
on the *same* OCR service and *same* ExpiryParser (`app/services/vision/ocr.py`,
`app/services/product/expiry_parser.py` — both reused, nothing rewritten), plus a
**barcode read for product identity only**. A phone photograph of a pack:

```
photo ──▶ quality gate (size/blur) ──▶ barcode (pyzbar, local) ──▶ product lookup
                                       │                             (catalog only, never create)
                                       └─▶ PaddleOCR text ──▶ ExpiryParser ──▶ candidate fields
                                                                                   │
                                          candidate review (editable) ──▶ quantity (human)
                                                                                   │
                                                                                   ▼
                                       BatchService + InventoryService (one atomic transaction)
```

The OCR results are **editable before anything is committed**, the quantity is
always typed by the shopkeeper (never guessed by OCR), barcodes only ever select
an existing product (never auto-create one, and never claim EXP/MFG/BATCH/MRP),
and the whole commit is a single atomic transaction through the existing domain
services.

## Old assumption vs new path

| Aspect | Before M17 | After M17 |
|--------|-----------|-----------|
| How batch data gets into stock | Manual `+ Receive stock` dialog; batch fields typed or left blank | Close-up photo → editable prefill via barcode + OCR |
| OCR role | Two places: M6 bill OCR + M13 experimental CCTV text tap | Reliable path is **close-up Smart Batch Receiving**; the CCTV OCR tap stays **off by default** (`PipelineConfig.ocr: bool = False`) and is documented as experimental |
| Barcode | Not modelled at all | `products.barcode` (unique per store) + pyzbar decode |
| Expiry reading from AI stream | M13 wrote OCR text/expiry-metadata observations (informational) | The CCTV tap still writes informational observations only; **only** the close-up intake can feed real batch data |
| Mutations | Human-driven, atomic | Human-confirmed, atomic (same domain services) |

## Hard rules honoured

- **No stock mutation before confirmation.** `POST /api/batch-intake/scan` is
  read-only (unit-tested: no rows change). Only `POST /api/batch-intake/confirm`
  commits, via `BatchService` + `InventoryService` in one transaction with
  try/except rollback.
- **Quantity is human-entered.** OCR never proposes a quantity; the confirm form
  requires a positive integer from the shopkeeper.
- **Barcode = identity only.** `PyZbarBarcodeDecoder` returns the code string;
  `_resolve_product` looks it up against the local `products` catalog scoped to the
  store. An unknown barcode yields `product_found: false` and the UI falls back to
  "Select product…" — nothing is auto-created.
- **Conservative reading.** If the image fails the quality gate
  (`min_short_side=480` / `min_long_side=960`, ≤15 MB, decodable image) or OCR +
  parser cannot produce any structured field and no barcode decodes, the scan
  returns `acceptable: false` with
  "Unable to confidently read package information." — no guessing.
- **Reuse > rewrite.** OCR (`OCRService`), `ExpiryParser`, `BatchService`,
  `InventoryService`, and the atomic mutation paths are all reused. The new package
  `app/services/batch_intake/` is a thin orchestration layer on top.
- **Offline-first.** Barcode decode and OCR run locally (PaddleOCR bootstrap excepted
  on a never-initialised machine — same documented caveat as M13). Images are
  processed in-memory and **discarded**; nothing is stored in PostgreSQL.
- **Error honesty.** `ImageDecodeError` / `ImageQualityError` / `ScanValidationError`
  → 422, `OcrUnavailableError` / `BarcodeUnavailableError` → 503, base
  `BatchIntakeError` → 500 (wired in `app/api/errors.py`).

## What was delivered

### Data layer
- `products.barcode` — VARCHAR(64), nullable, indexed, with a
  `UNIQUE (store_id, barcode)` constraint (migration `c4f5a6b7c8d9`,
  down_revision `d9e4a30f8b21`). `alembic heads` = `c4f5a6b7c8d9`);
  `tests/test_migrations.py` EXPECTED_HEAD updated and the migration round-trips.

### Service package (`backend/app/services/batch_intake/`)
- `barcode_decoder.py` — `BarcodeDecoder` protocol, `PyZbarBarcodeDecoder`
  (bootstraps `ctypes.util.find_library` for libzbar before importing pyzbar),
  `FakeBarcodeDecoder`, `make_barcode_decoder()` (→ `None` when zbar is missing so
  the service degrades gracefully).
- `package_ocr.py` — `QualityGateConfig`, `decode_image_bytes`, `check_quality`,
  `PackageOCRProcessor` (lazy PaddleOCR load via `app.services.vision.ocr`).
- `candidate.py` — `DecodedBarcode`, `PackageScanCandidate`, `PackageScan`
  (with `from_parsed`) plus the `UNABLE_TO_READ_MESSAGE` constant.
- `batch_intake_service.py` — `scan_package` (read-only: decode + OCR + parser +
  local product resolution) and `confirm_receipt` (atomic batch + receive; reuses
  `BatchService._validate_batch`, `_normalize_batch_number`, `get_batch`).
- `errors.py` — typed error hierarchy listed above.

### API (`backend/app/api/routers/batch_intake.py`)
- `POST /api/batch-intake/scan` — multipart `file` + `store_id` → `BatchScanRead`
  (never mutates).
- `POST /api/batch-intake/confirm` — `BatchConfirmIn` → 201 `BatchReceiptRead`
  (atomic).

### Frontend
- `src/lib/api/types.ts` — `Product.barcode`, `BatchScanCandidate`,
  `BatchScanResponse`, `BatchConfirmIn`, `BatchReceipt`.
- `src/lib/api/batchIntake.ts` — `batchIntakeApi.scan` (raw `fetch` +
  `FormData`, since the JSON-only `client.ts` can't do multipart) and
  `batchIntakeApi.confirm`.
- `src/pages/ReceiveSmart.tsx` — `/inventory/receive`: 7-step workflow
  (Capture → Scan → Review → Product → Quantity → Confirm → Done), preview,
  editable prefill, unknown-barcode manual fallback, human quantity, success
  receipt, low-quality/422 error state with retry guidance.
- `src/App.tsx` — `/inventory/receive` route.
- `Inventory.tsx` — "+ Smart Batch Receiving" CTA to the new page.
- `Dashboard.tsx` — "Smart Batch Receiving" card with `[+ Receive New Stock]` and
  the 5 most recent batches from real Postgres.
- `CameraDetail.tsx` — explicit hint card: continuous cameras do **not** read
  printed expiry at distance; use the close-up intake instead.

## Verification

- **Backend:** `tests/test_batch_intake.py` — **24 tests**: scan is read-only
  (no row counts change), quality-gate + image-decode 422s, barcode resolution +
  store scoping, unknown-barcode → `product_found false` (no auto-create), atomic
  confirm (single batch + receive + no partial rows on failure), batch reuse on
  same product, invalid month/date handling, expiry_quantity/none syntax, zero and
  negative quantity rejected, missing store/product 422, HTTP multipart scan +
  confirm 201, barcode round-trip on the product resource.
- **Real-AI smoke (offline):** `tests/test_batch_intake_real_ai.py` — **2 tests**,
  marker `real_ai`: real PaddleOCR reads a rendered label
  (EXP 15/12/2026 → `date(2026,12,15)`, M24031, ₹14.00) via `ExpiryParser`, and
  pyzbar decodes the embedded Code-39 `8901234567890`. Fully offline.
- **Full backend regression:** **221 passed** `(pytest tests/ -q)`, including the
  migration up/down round-trip at the new head `c4f5a6b7c8d9`.
- **Frontend:** `npx tsc -b` clean; `npx vitest run` **75 passed across 19 files**
  (new `ReceiveSmart.test.tsx`: full happy path, unknown-barcode manual fallback,
  low-quality 422 state); `npm run build` succeeds.

## Known caveats (accepted)

- Same PaddleOCR first-run bootstrap caveat as M13 (model cache under
  `~/.paddleocr`); after first run everything is offline.
- Barcode decoding is Code-39/Code-128/EAN/etc. as supported by local zbar; very
  low-contrast or creased labels may fail the (intentionally strict) quality gate —
  the shopkeeper retakes the photo or enters values manually.
- Confidence is not used to reject a candidate on its own; the quality gate +
  "at least barcode OR one structured field parsed" rule keeps the bar honest.
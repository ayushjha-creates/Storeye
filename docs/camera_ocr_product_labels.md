# Camera OCR — Product Label Reads

Hold a package up to a camera and Storeye can read its printed **product name,
manufacturing date, expiry date and MRP**, then match the name to a product
already in the store catalog (adding the catalog price). This is an **assistive
observation**, not a stock movement.

## What it does / does not do

- **Does** run the opt-in OCR tap on a live camera and write `EXPIRY_METADATA`
  observations (raw text, MFG, EXP, MRP, warnings, and — when the name matched —
  `product_id`, `recognized_product_name`, `label_match_score`, `matched_label`,
  `catalog_price`).
- **Does not** create products, change inventory, create batches, or mutate any
  catalog data. It is read-only against the catalog.
- **Does not** guess. If the printed name does not convincingly match a known
  alias, no product is attached and the UI shows **"Unrecognized label"**.

## Enabling it

Per camera, set the nested pipeline flag in the camera config:

```json
{ "config": { "pipelines": { "person_detection": true, "product_detection": true, "ocr": true } } }
```

In the UI: **Cameras → edit → "Read product labels (OCR)"**. The camera form
writes the nested `config.pipelines` shape the runtime reads. OCR runs every
`ocr_interval` frames (default 30) so it does not slow person/product tracking.

If the local PaddleOCR weights cannot load, the camera **still starts** without
OCR and the status reports OCR disabled — a missing model never takes the camera
down.

## Name matching (conservative, deterministic)

`backend/app/services/product/name_matcher.py`:

1. Normalize case + punctuation and collapse whitespace.
2. Skip noise lines: pure numbers, date-like strings, and lines containing
   `EXP/EXPIRY/MFG/MFD/MRP/BATCH/LOT/USE/BEST BEFORE/DATE/PRICE/...`.
3. Score each remaining line against every product alias: the product `name`,
   its `brand`, and each explicit `ai_classes` entry. Aliases shorter than 4
   significant characters are ignored.
4. Accept the best line only if it scores `>= 0.86`. Ties break by product name
   then id, so identical text always resolves to the same product.

Aliases come only from what the store already catalogued; there is no open-world
recognition and no learned OCR-to-catalog mapping.

## Where it shows up

- **Camera page** — `ProductLabelReads` panel lists the most recent reads with
  the recognized name (or "Unrecognized label"), MFG, EXP (+ precision), label
  MRP, catalog price, OCR confidence and the raw text.
- **API** — `GET /api/observations?camera_id=...&observation_type=EXPIRY_METADATA`
  returns `details` and `product_id` for each read.

## Honest limits

- PaddleOCR is unreliable on curved, glare-hit, tiny, rotated or fast-moving
  text; unreadable fields stay empty for human review.
- Camera OCR is far less reliable than **Smart Batch Receiving**, which uses
  barcode/GTIN as the authoritative path. Prefer barcode for stock intake.
- Dates and MRP are suggestions only; always confirm on the package.

## Tests

- `backend/tests/test_name_matcher.py` — normalization, exact/containment/brand/
  `ai_classes` matches, noise rejection, determinism, no false positives.
- `backend/tests/test_observations.py::test_ocr_expiry_observation_resolves_catalog_product`
  and `..._unmatched_label_stays_unattached` — writer resolves (or refuses to
  resolve) the catalog product and never mutates inventory.
- `backend/tests/test_edge_ai.py::test_runtime_survives_unavailable_ocr_model` —
  a missing OCR model does not stop the camera.
- `frontend/src/components/camera/ProductLabelReads.test.tsx` — matched,
  unrecognized and empty states.

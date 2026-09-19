# M32 — Product & Shelf Detection That Actually Works (open-vocabulary)

Status: **code + tests complete (backend 587 / frontend 164); real YOLO-World
inference verified on this machine. Physical store-camera verification still
needs a human at the store.**

The user report was blunt and correct: *"shelf detection is still not working,
and also product detection — anyhow make it do so."* This milestone fixes the
**root cause** honestly instead of faking counts, and it never weakens the hard
rules: no fabricated detections, no cloud AI, no face recognition, offline-first,
local PostgreSQL authoritative, no frontend-side inference.

## Root cause (measured, not guessed)

1. **The only product model was a 55-class fine-tuned FMCG checkpoint**
   (`models/shelf/shelf_model.pt`): Complan, Everyuth, Glucon-D, Nutralite,
   Nycil, Sugar Free, Sugar Lite. It has **no biscuit / general grocery class**,
   so a normal store's shelves produce almost nothing. That is why "biscuit is
   not detected" — the object is simply out-of-distribution.
2. **There is no shelf-detection model at all.** "Shelf detection" is operator
   `shelf_regions` + product-box geometry (M15/M30). With (1) detecting nothing,
   shelves always looked empty/unknown.
3. **The live overlay mis-rendered real detections.** Observations store `bbox`
   in **pixels** (`[x1,y1,x2,y2]`), but `DetectionOverlay.tsx` divided by 100 as
   if boxes were normalized 0–100. Demo boxes are 100×100 so it was hidden; on a
   real 1280×720 camera the boxes were drawn far off-screen.

## The fix: text-prompted open-vocabulary detection (YOLO-World)

`ultralytics` already ships **YOLO-World**, a zero-shot detector conditioned on
text prompts. Give it the store's own product words and it detects *those*
objects — no retraining, no cloud. This is the real, offline answer to "detect
my products".

### Backend

1. **New vision service** `app/services/vision/world_detector.py`
   (`WorldProductDetector`): wraps `ultralytics.YOLOWorld`, `set_prompts(...)`
   encodes prompt words with CLIP and installs the class names, `detect(frame)`
   returns the shared `Detection`/`DetectionResult` shape. Empty prompts → a
   **concrete no-op** (never a hidden vocabulary). Weights resolve to
   `models/shelf/yolov8s-worldv2.pt` else Ultralytics' default checkpoint; CLIP
   text encoder (`ViT-B-32.pt`, ~338 MB) is fetched once into
   `backend/weights/clip/` and everything runs offline afterwards.
2. **Adapter** `WorldProductDetectorModel` in
   `app/edge/models/product_detector.py` (`set_prompts`, `detect_frame`),
   mirroring the existing `ProductDetectorModel` interface.
3. **Registry** `ModelRegistry.new_product_detector(detector="world"|"shelf",
   prompts, conf)`. YOLO-World is prompt-conditioned, so instances are cached by
   `(path, prompt_tuple)` — cameras with the same vocabulary share one model +
   CLIP encoder; memory stays bounded.
4. **Config** `PipelineConfig.product_detector` (`"world"` default) and
   `product_prompts: List[str]`, with validation (`world|shelf`).
5. **Runtime** `EdgeRuntime.add_camera` builds the per-camera product model and
   is **fail-soft**: if the weights/CLIP can't load, only the product tap is
   disabled (`pipelines.product_detection = False`) and the camera still runs —
   the same rule already used for OCR.
6. **API** `_config_from_camera(cam, db)` forwards operator prompts; when none
   are given it derives the vocabulary from the store's **own catalog**
   deterministically (`ai_classes` → `brand` → `name`, deduped, capped at 40).
   These are real catalog terms — nothing invented. Camera schema validates the
   new keys (flat and nested `pipelines`).
7. **Normalized boxes** `bbox_norm` (`[x1,y1,x2,y2]` in 0..1) is now carried on
   person and product events and stored in observation `details`. Pixel `bbox`
   is unchanged, so M15/M30 stay intact.
8. **Catalog resolution** for open-vocab prompt names: the ObservationWriter
   falls back to the same conservative `ProductNameMatcher` used for OCR, so a
   prompt like a product/brand name attaches `product_id` honestly.

### Frontend

- `DetectionOverlay.tsx` now prefers `details.bbox_norm` (percentages), with the
  legacy 0–100 `(x,y,w,h)` path kept for demo data — real camera boxes finally
  render in the right place.
- `Cameras.tsx` gains a **Product detector** selector (`world`/`shelf`) and a
  **Product prompts** field (comma/newline separated, blank = derive from the
  catalog), persisted in the nested `config.pipelines` shape the runtime reads.

## What was verified on this machine (real, not claimed)

- CLIP weights downloaded and **SHA-256 verified** against the known
  `40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af`.
- `WorldProductDetector` on a real photo (`bus.jpg`) with prompts
  `["person","bus","handbag"]` returned real detections
  (`person 0.92/0.91/0.89/0.64`, `bus 0.89`) — the zero-shot path works offline.
- Load ~3 s (weights cached), first inference ~8 s warm-up, then normal.
- `alembic check` clean (no schema change — config/memory only).

## Honest limits (also in `docs/model_capabilities.md`)

- YOLO-World detects **only what a prompt/catalog term describes**; with no
  prompts and no catalog it detects nothing. Accuracy depends on prompt wording.
- It is **not** an exact counter — occlusion, angles and overlap cause misses and
  occasional doubles. Detections are observations, never inventory truth.
- The legacy `shelf` model remains selectable for stores already using its 55
  classes. First use needs a one-time model/CLIP download; after that it is fully
  offline.

## Verification gates

- Backend: new `tests/test_world_detector.py` (11) plus pipeline `bbox_norm`,
  writer `bbox_norm`/name-fallback, `_config_from_camera` prompts/derivation,
  camera-schema validation, and a runtime fail-soft product-model test.
- Frontend: `DetectionOverlay.test.tsx` (3) + a Cameras detector/prompts
  persistence test. `npx tsc -b`, `npx vitest run` (164), `npm run build` green.

## Remaining (needs a human + a real camera)

Point a USB camera at a shelf with a few known products, add prompts (or a
catalog), start the camera, and confirm on the live view that product boxes
appear over those products and that `ShelfMonitor` occupancy changes. Only then
record it as verified — no fabricated detections or performance numbers.

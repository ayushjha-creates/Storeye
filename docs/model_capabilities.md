# Storeye — Model Capabilities & Limits (honest reference)

This document states **exactly what the installed models can and cannot do**.
It is deliberately unflattering where the truth is limited: Storeye must never
imply capabilities the models do not have. Asset files, sizes and licenses live
in [`docs/model_assets.md`](model_assets.md); this file is about behaviour.

> Rule of thumb used throughout the product: **a model output is a candidate,
> never a fact.** Catalog matching is always explicit (barcode or an operator's
> `Product.ai_classes` mapping). Nothing invents a product, shelf, count, or
> identity.

---

## 1. Person detection + tracking

| | |
|---|---|
| File | `models/yolo/yolo11n.pt` |
| Architecture | Ultralytics YOLO11n, `detect`, 80 COCO classes |
| Used for | `person` class only (class id 0) |
| Tracker | ByteTrack (`bytetrack.yaml`), one tracker instance **per camera** |

**Can:** detect multiple people, give stable local track ids while a person
remains continuously visible, and survive brief occlusions (ByteTrack buffer).

**Cannot:**
- Identify who a person is — no faces, no biometrics, no names, ever.
- Guarantee a track id survives a full occlusion or a long exit; ByteTrack will
  re-create ids. M27 adds guarded same-camera re-acquisition so a re-created
  track can rejoin its previous **anonymous** global id, but this is
  heuristical, not a guarantee.
- Count people exactly under heavy crowding or when people are partially hidden
  behind shelves.

## 2. Anonymous Re-ID (journey association)

| | |
|---|---|
| Default provider | `torch` — torchvision ResNet18 ImageNet penultimate features (512-d) |
| Optional | `openvino` OMZ `person-reidentification-retail-0287` (256-d) |
| Storage | **in-memory only**; embeddings are never persisted (enforced by test) |

**Can:** group a person's local tracks into one anonymous global id across
cameras using appearance + time + a configured camera-transition graph.

**Cannot:**
- Prove identity. ResNet18 ImageNet features are generic visual descriptors, not
  a Re-ID-trained network; different people can look alike and the same person
  can look different (lighting, pose, clothing changes). This is why thresholds
  are conservative.
- Merge two **concurrent** same-camera tracks. That is intentional: a false merge
  of two people corrupts analytics far worse than a missed match.
- Reconnect across a long absence (`GLOBAL_PERSON_TIMEOUT_SECONDS`, default
  30 min) — a later visit starts a new anonymous session by design.

## 3. Product / shelf-object detector

Storeye supports **two** product detectors, selected per camera:

| `pipelines.product_detector` | File | What it is |
|---|---|---|
| `world` *(default, M32)* | `models/shelf/yolov8s-worldv2.pt` + `weights/clip/ViT-B-32.pt` | Ultralytics **YOLO-World** open-vocabulary detector, text-prompted |
| `shelf` (legacy) | `models/shelf/shelf_model.pt` | fine-tuned Ultralytics `detect`, **55 fixed classes** |

### 3a. Open-vocabulary `world` (default)

YOLO-World is **text-conditioned**: the camera is given a list of prompt words
(`pipelines.product_prompts`, or automatically the store's own catalog — each
product's `ai_classes`, then `brand`, then `name`) and it detects *those* objects
on the current frame. This is the honest fix for "biscuit isn't detected": add
`biscuit packet` (or a product named/branded that way) and the model looks for it.

| | |
|---|---|
| Weights | `models/shelf/yolov8s-worldv2.pt` (~28 MB; downloaded by Ultralytics if absent) |
| Text encoder | CLIP `ViT-B-32.pt` (~338 MB) at `backend/weights/clip/ViT-B-32.pt` (downloaded once) |
| Prompts | operator list in `camera.config.pipelines.product_prompts`, else derived from the catalog (cap 40) |
| Sharing | one model instance per distinct prompt set (prompt-conditioned) |

**Can:** detect arbitrary products/packaging an operator (or the catalog) names
as a prompt — biscuits, milk cartons, soap, etc. — **fully offline after the
one-time weight download**; map a detected prompt back to a catalog product via
the same conservative name matcher used for OCR.

**Cannot:**
- Detect anything not described by a prompt. With no prompts and no catalog it
  is a **concrete no-op** — it never falls back to a hidden vocabulary or invents
  a class.
- Be relied on for exact counts; overlapping/angled/occluded packs are missed or
  double-counted, and prompt wording materially changes accuracy.
- Add inventory truth: detections are **observations only** (see below).

### 3b. Legacy fine-tuned `shelf` (55 classes)

| | |
|---|---|
| File | `models/shelf/shelf_model.pt` |
| Architecture | fine-tuned Ultralytics `detect`, **55 classes** |
| Used for | the `product` pipeline (`ProductDetectorModel`) |

**Measured class list (all 55):**

```
Complan Classic Creme
Complan Kesar Badam
Complan Nutrigro Badam Kheer
Complan Royal Chocolate
\ 'Complan Pista Badam'   (raw class string contains a leading backslash/tick)
EY AAAM TULSI TURMERIC FACEWASH50G
EY ADVANCED GOLDEN GLOW PEEL OFF M- 50G
EY ADVANCED GOLDEN GLOW PEEL OFF M- 90G
EY ADVANCED GOLDEN GLOW PEEL OFF M. 50G
EY ADVANCED GOLDEN GLOW PEEL OFF M. 90G
EY EXF WALNUT SCRUB AYR 200G
EY HALDICHANDAN FP HF POWDER 25G
EY HYD-EXF WALNT APR SCRUB AYR100G
EY HYDR - EXF WALNUT APRICOT SCRUB 50G
EY NAT GLOW ORANGE PEEL OFF AY 90G
EY NATURALS NEEM FACE WASH AY 50G
EY RJ CUCUMBER ALOEVERA FACEPAK50G
EY TAN CHOCO CHERRY PACK 50G
EY_SCR_PURIFYING_EXFOLTNG_NEEM_PAPAYA_50G
Everyuth Naturals Body Lotion Nourishing Cocoa 200ml
Everyuth Naturals Body Lotion Rejuvenating Flora 200ml
Everyuth Naturals Body Lotion Soothing Citrus 200ml
Everyuth Naturals Body Lotion Sun Care Berries SPF 15 200ml
Glucon D Nimbu Pani 1-KG
Glucon D Nimbu Pani 1.KG
Glucon D Regular 1-KG
Glucon D Regular 1.KG
Glucon D Regular 2-KG
Glucon D Regular 2.KG
Glucon D Tangy orange 1-KG
Glucon D Tangy orange 1.KG
Nutralite ACHARI MAYO 300g-275g-25g-
Nutralite ACHARI MAYO 30g
Nutralite CHEESY GARLIC MAYO 300g-275g-25g-
Nutralite CHEESY GARLIC MAYO 30g
Nutralite CHOCO SPREAD CALCIUM 275g
Nutralite DOODHSHAKTHI PURE GHEE 1L
Nutralite TANDOORI MAYO 300g-275g-25g-
Nutralite TANDOORI MAYO 30g
Nutralite VEG MAYO 300g-275g-25g-
Nycil Prickly Heat Powder
SUGAR FREE GOLD 500 PELLET
SUGAR FREE GOLD POWDER 100GM
SUGAR FREE GOLD SACHET 50
SUGAR FREE GOLD SACHET 50 SUGAR FREE GOLD SACHET 50
SUGAR FREE GRN 300 PELLET
SUGAR FREE NATURA 500 PELLET
SUGAR FREE NATURA DIET SUGAR
SUGAR FREE NATURA DIET SUGAR 80GM
SUGAR FREE NATURA SACHET 50
SUGAR FREE NATURA SWEET DROPS
SUGAR FREE NATURAL DIET SUGAR 80GM
SUGAR FREE NATURA_ POWDER_CONC_100G
SUGAR FREE_GRN_ POWDER_CONC_100G
SUGARLITE POUCH 500G
```

**Can:** detect those specific SKUs/pack variants when they are clearly visible.

**Cannot — read this before claiming product AI:**
- **There is no `biscuit` class (no Parle/Britannia/Marie/Good Day/etc.).** A
  biscuit packet is out-of-distribution and will not be detected as a product.
  This is the honest reason "biscuit isn't detected".
- It is **not** a general grocery or package detector. Arbitrary products, fresh
  produce, unbranded items and competitor brands are not in the class list.
- Near-duplicate classes exist (e.g. `Glucon D Regular 1-KG` vs `1.KG`); it may
  confuse pack variants.
- Small, angled, occluded or glare-heavy packs degrade accuracy.

**What Storeye does with an unknown class:** it records the detection as an
**unknown/unmapped candidate** (class name preserved) and shows
`Unknown product — map to catalog` — it is **never** guessed into the catalog.
These are exposed as an explicit read-only list at
`GET /api/intelligence/product-candidates` (`ProductCandidateRead`), and on the
Product Intelligence page as **"Product candidates"**. To make a class count as
a product, an operator sets `Product.ai_classes` to the exact class string (for
`world`, the prompt name is also matched to the catalog by name). A real biscuit
with the legacy model needs either a retrained model or a barcode scan; with the
default `world` detector it needs a prompt/catalog term describing it.

## 4. OCR

| | |
|---|---|
| Provider | PaddleOCR PP-OCRv6 (locals only, first-use bootstrap) |
| Used for (receiving) | close-up package photos: batch no., MFG, EXP/MRP, MRP |
| Used for (camera) | opt-in live-camera label reads (`pipelines.ocr=true`) |

**Can:** read printed dates/text from a close, well-lit package photo, and — when
the opt-in camera OCR tap is enabled — periodically read a package held up to a
live camera and match the printed **name** to the store catalog.
**Cannot:** reliably read curved, glare-hit, tiny or rotated text; it never
invents a date — unreadable fields stay empty for human review. OCR output is a
suggestion requiring confirmation; the barcode/catalog path is authoritative.

Camera OCR is **assistive only**: it writes `EXPIRY_METADATA` observations
(product name, MFG/EXP, MRP, catalog price when the name matched) and **never**
changes inventory, batches or stock. Unmatched labels are shown as
"Unrecognized label" — the matcher refuses label noise (dates, `MRP`/`EXP`/`MFG`/
`BATCH`) and never guesses. Name matching is exact/containment against the
product `name`, `brand` and `ai_classes` (see
[`docs/camera_ocr_product_labels.md`](camera_ocr_product_labels.md)). It requires
the PaddleOCR weights; if they cannot load, the camera still starts and OCR is
reported as disabled.

## 5. Barcode / GTIN

| | |
|---|---|
| Provider | `pyzbar` + system `libzbar` |
| Used for | EAN/UPC/GTIN/Code-39 decode in receiving |

**Can:** decode a barcode to a GTIN, matched against the product catalog.
**Cannot:** decode a damaged/obscured barcode; an unregistered GTIN is reported
as "barcode not registered", never assumed.

## 6. Shelf intelligence

There is **no shelf-detection model**. "Shelf intelligence" is region geometry:
an operator configures `camera.config.shelf_regions` (`code`, optional `label`,
`bbox` in image pixels), and Storeye associates detected product boxes whose
centre falls inside a region and computes an occupancy ratio. The product boxes
come from whichever detector the camera uses — with the default `world` detector
this means occupancy now reflects the products you actually prompted/listed in
the catalog, not a fixed 55-class vocabulary. Region codes must
match `Shelf.code`. If occupancy is unknown it reports `UNKNOWN` — it does not
fabricate a shelf count. When observations span at least 3 wall-clock
minute-buckets the occupancy is **temporally smoothed** (median of per-bucket
occupancies, `occupancy_method="median_60s"`, `occupancy_samples=N`) so a single
detection spike does not flip the state; otherwise the raw value is reported.
States are `UNKNOWN` (no evidence — never alerts), `EMPTY_VISIBLE` (→ critical
`SHELF_EMPTY` "refill now" alert) and `LOW_VISIBLE` (at or below half full,
`LOW_OCCUPANCY_FRACTION=0.5` → `LOW_SHELF_OCCUPANCY` "refill soon"); both set
`refill_recommended=true` and are also re-emitted when a reconciliation run
completes (`details.trigger="reconciliation"`). These are **informational
alerts only** — they never create or change stock.

## 7. Summary table

| Question | Honest answer |
|---|---|
| Can it detect people? | Yes (COCO person). |
| Can it recognise/name a person? | **No.** Anonymous ids only. |
| Can it count one person once? | Yes, after M27 guarded re-acquisition; not infallible. |
| Can it detect biscuits? | **Yes with the default `world` detector if prompted** (e.g. `biscuit packet`); **no** with the legacy 55-class model. |
| Can it detect a general product? | Yes with `world` (any prompted/catalog term); only the 55 listed classes with the legacy model. |
| Does it auto-detect shelves? | **No.** Regions are configured manually. |
| Does it use the cloud / faces? | **No.** Fully local, no biometrics. |
| Can it read a label held to the camera? | Opt-in OCR; assistive only, never changes stock. |
| What happens to unknown classes? | Recorded as an unknown candidate; never guessed. |

## 8. How to extend coverage honestly

1. **Barcode first** for receiving (`/api/batch-intake/scan` + catalog mapping).
2. For vision, prefer the default `world` detector: add `camera.config.pipelines
   .product_prompts` (or keep product `name`/`brand`/`ai_classes` accurate so the
   vocabulary derives automatically). No retraining required — but a product the
   prompts don't describe will not be detected.
3. To map an already-detectable legacy class to the catalog, add its exact class
   string to `Product.ai_classes`; that maps a class, it does not add new ones.
4. New classes for the **legacy** model require retraining/replacing
   `models/shelf/shelf_model.pt` (see
   [`docs/dataset_requirements.md`](dataset_requirements.md)); document the new
   class list here when that happens. First inference downloads the YOLO-World
   and CLIP weights once; after that both detectors run fully offline.

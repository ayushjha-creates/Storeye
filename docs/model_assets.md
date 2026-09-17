# Storeye — AI Model Assets

Storeye's AI runs **entirely on the edge**. Every model below is a local file.
Nothing is downloaded at runtime. All assets are validated (never fetched) by:

```bash
./scripts/storeye models                          # or
(cd backend && ./.venv/bin/python -m app.deployment.model_check --deep)
```

Exit code **0** = every required asset is present; **1** = something is missing.

---

## 1. Asset inventory

| Name | Purpose | Location (default) | Provider | Size | Source | License |
|------|---------|--------------------|----------|------|--------|---------|
| YOLO11n person detector | person/people bounding boxes (journey pipeline) | `models/yolo/yolo11n.pt` | Ultralytics YOLO11n (COCO person class) | 5.4 MB | shipped in repo | AGPL-3.0 (Ultralytics) |
| Shelf/product detector | 55-class Indian-FMCG retail product detection (e.g. Complan, Glucon-D) | `models/shelf/shelf_model.pt` | fine-tuned Ultralytics `detect` model | 6.0 MB | shipped in repo | internal / Ultralytics-derivative |
| Re-ID — torch (default) | anonymous appearance embeddings (512-d) | `~/.cache/torch/hub/checkpoints/resnet18-f37072fd.pth` (override: `REID_TORCH_WEIGHTS_PATH`) | torchvision ResNet18 ImageNet | 45 MB | `download.pytorch.org` (bootstrap) | BSD-3-Clause |
| Re-ID — OpenVINO (optional) | anonymous embeddings (256-d) | `models/reid/person-reidentification-retail-0287.{xml,bin}` (override: `REID_OV_MODEL_PATH`) | Intel Open Model Zoo `person-reidentification-retail-0287` | ~6 MB | Open Model Zoo (bootstrap) | Apache-2.0 |
| OCR — PaddleOCR | close-up package text (MFG/EXP/MRP) for Smart Batch Receiving | `~/.paddlex/official_models/*` | PP-OCRv6 (det + rec + textline) | several MB | PaddleOCR (first use) | Apache-2.0 |
| Barcode backend | GTIN/EAN/UPC/Code-39 decode | system library (`/opt/homebrew/lib/libzbar.dylib`, `/usr/lib/x86_64-linux-gnu/libzbar.so.0`, …) | zbar via `pyzbar` | n/a | OS package manager | LGPL-2.1-only |
| Re-ID — stub (`REID_PROVIDER=stub`) | deterministic embedding for tests/demo | in-memory only | built-in | 0 | repo | MIT |

> Runtimes: torch/torchvision come transitively via `ultralytics`. `openvino`
> and system `zbar` are NOT Python packages of the base `requirements.txt`:
> `openvino` is optional; `zbar` is installed via your OS package manager.

## 2. Download timing — the offline boundary (STATE A/B/C)

Installation/onboarding is the **only** time the internet is needed:

| State | Description | Works |
|-------|-------------|-------|
| **A — Fresh machine + internet** | `scripts/setup.sh` installs deps; fetch Re-ID weights + OCR models (below); run `model_check` | full install |
| **B — Prepared edge machine (no internet)** | deps + weights already staged (`~/.cache/torch`, `~/.paddlex`, repo `models/`, `zbar`) | **runtime fully offline** — this is the normal operating state |
| **C — Fresh machine + zero internet** | nothing pre-staged | **NOT SUPPORTED** — do not claim otherwise |

Storeye exports are **never** fetched automatically (`model_check` refuses to
download). Two commands cover the bootstrap download:

```bash
# 1. torch Re-ID weights (once, online):
(cd backend && ./.venv/bin/python - <<'PY'
import torch, torchvision
torch.hub.load_state_dict_from_url(
    "https://download.pytorch.org/models/resnet18-f37072fd.pth", progress=True)
PY
)

# 2. PaddleOCR official models (downloaded on the first OCR use while online;
#    then ~/.paddlex can be copied between identical-OS machines).
# Alternatively run the OCR smoke test once while online:
(cd backend && ./.venv/bin/python -m pytest tests/test_batch_intake_real_ai.py -q)
```

## 3. Offline staging recipe (STATE B)

To build a fully-offline edge machine from an online one:

```
1. On the online machine, finish STATE A.
2. Copy the whole repo (including models/).
3. Copy/cache these hidden dirs to the SAME absolute home path on the target:
     ~/.cache/torch/hub/checkpoints/     (resnet18-f37072fd.pth)
     ~/.paddlex/official_models/          (PP-OCRv6*)
   (REID_TORCH_WEIGHTS_PATH / REID_OV_MODEL_PATH lets you relocate them.)
4. Install the same Python/node/OS packages + system `zbar`.
5. On the target:  ./scripts/setup.sh  →  ./scripts/storeye models   →  storeye doctor
```

## 4. What `model_check` verifies

- `models/yolo/yolo11n.pt` exists, is a real file, ≥ 64 KiB (Git-LFS/pointer guard).
- `models/shelf/shelf_model.pt` same.
- Configured `REID_PROVIDER` assets: torch weights file, or OpenVINO `.xml`+`.bin` + `openvino` import.
- `REID_ENABLED=false` → Re-ID check is skipped (stub acceptable in tests/demo).
- PaddleOCR importable; model-cache WARN if not yet populated (will download on first use — bootstrap only).
- Barcode: `pyzbar` importable and (with `--deep`) the system `libzbar` resolvable.

`--deep` also probes the heavy imports (torch/torchvision/PaddleOCR) and the
real `libzbar` load. Use `--fast` in the setup/doctor loops to keep them quick.
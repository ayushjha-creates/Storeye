# Storeye — Camera Setup

Storeye cameras are **configuration metadata** (a `Camera` row in PostgreSQL);
the AI runtime reads each camera's `config` to choose a capture source and
which pipelines to run. Raw video is **never persisted**.

> Demo/template cameras (from `scripts/seed_demo.py`) are `camera_type="file"`
> with a semantic `config.kind` (e.g. `product`/`person`) and **no source path**:
> they are driven by the demo generator, not real video. Real cameras need a
> concrete `source`.

---

## 1. Camera model + sources

| `camera_type` | Meaning | `config.source` |
|---------------|---------|------------------|
| `usb` | webcam attached to the edge node | integer device index (default `0`) |
| `file` | local video file (also demo/tests) | absolute or relative path to the file |
| `rtsp` | IP camera stream (**reserved/future**) | stream URL (`streamUrl`) |

`config.kind` is validated at the API layer and must be one of `usb|file|rtsp`.

## 2. Registering a camera (API)

REST endpoint: `POST /api/cameras` (`backend/app/api/routers/cameras.py`).
List: `GET /api/cameras` · update `PATCH /api/cameras/{id}` · delete `DELETE /api/cameras/{id}`.

```bash
curl -s http://localhost:8000/api/cameras \
  -H 'Content-Type: application/json' \
  -d '{
    "store_id": "<your-store-uuid>",
    "name": "Aisle 1 Cam",
    "location": "Main Grocery Aisle",
    "camera_type": "file",
    "is_active": true,
    "config": {
      "kind": "file",
      "source": "/var/storeye/media/aisle1.mp4",
      "person_detection": true,
      "product_detection": true,
      "ocr": false,
      "zone_id": "<zone-uuid>",
      "zones": [{"zone_id": "<zone-uuid>", "bbox": [0.1, 0.3, 0.9, 0.95]}],
      "next_cameras": ["<camera-id>"],
      "reid": {"embedding_refresh_interval_seconds": 10}
    }
  }'
```

Meaningful `config` keys (see `backend/app/schemas/camera.py` + `backend/app/edge/config.py`):

| Key | Type | Purpose |
|-----|------|---------|
| `kind` | `usb\|file\|rtsp` | capture source type |
| `source` | str | device index, file path, or (future) URL |
| `streamUrl` | str | rtsp alternative |
| `person_detection` / `product_detection` / `ocr` | bool | per-camera pipeline switches |
| `zone_id` | str | primary physical zone this camera observes (journeys) |
| `zones` | list[`{zone_id, bbox:[x1,y1,x2,y2]}`] | normalized foot-point regions for zone enter/exit |
| `next_cameras` | list[str] | allowed camera transitions (empty = any) |
| `reid.*` | object | per-camera Re-ID tuning (e.g. embedding refresh interval) |

## 3. Edge runtime sources (`backend/app/edge/config.py`)

- `file` → a video file (`source`), e.g. from `data/` or `/var/storeye/media/`.
- `usb` → `device_index` (integrer `source`), default `0`.
- `rtsp` → reserved; requires the runtime to gain a stream adapter. Untested — **NOT VERIFIED**.

## 4. Validating recorded cameras

```bash
./scripts/storeye doctor --fast     # reports camera count + shape issues
```

The doctor warns on: unknown `camera_type`, a real source camera without a
`source`/`streamUrl`/`device_index`, or an rtsp camera lacking a URL. It does
**not** stream or open devices (read-only).

## 5. Known good configurations

| Hardware | `camera_type` | `config` |
|----------|---------------|----------|
| USB webcam | `usb` | `{"kind":"usb","source":"0","person_detection":true}` |
| Local clip (loop/test) | `file` | `{"kind":"file","source":"/abs/path/clip.mp4","person_detection":true,"ocr":true}` |
| Demo catalog | `file` | demo seed (no source; generated observations) |

## 6. Not verified in this milestone

Live camera lifecycle (ONLINE → OFFLINE → recovery) with a real physical
camera, USB capture rates on target hardware, and multi-camera Re-ID across
simultaneous streams are documented but **NOT VERIFIED** in the M22/M23
verification pass. Run a physical-camera soak test before fielding.

## 7. Mobile phone capture (no camera needed)

For **batch receiving** you do not need a connected camera at all: photograph a
pack with your phone, copy the photo over USB into the intake folder
(`backend/data/intake/`, override `STOREYE_INTAKE_DIR`), and the M25 watcher
feeds it through the same close-up pipeline (barcode + PaddleOCR + ExpiryParser)
with a human review gate. Capture rules are the same as for an in-browser
photo: flat, well-lit, close-up, filling the frame. See
`docs/mobile_usb_intake.md`.
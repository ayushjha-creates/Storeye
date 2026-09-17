# Mobile-to-Edge USB Intake Bridge (M25)

Storeye's batch receiving normally needs a browser on the same machine as the
edge node. M25 removes that requirement: your **phone is the camera**, the
**laptop/edge node stays the computer**.

The phone photographs a pack next to a scale counter. When the photo is copied
over USB into a watched folder on the edge node, Storeye picks it up and runs it
through the **exact same M17 pipeline** (barcode → OCR → ExpiryParser → catalog
lookup) with **no new AI**, **no cloud**, and **no second review thread**. The
result appears in the Smart Batch Receiving screen as a candidate that still
needs the usual human confirmation.

```
phone 📱 (camera only)                 edge node (all compute)
┌──────────────────────┐   USB copy    ┌─────────────────────────────────────────┐
│ photograph the pack  │ ────────────▶ │ <intake_dir>/        (weird-name .jpg)   │
│ then drag the photo  │               │      │ watcher polls every 1s           │
│ to the SCOPE drive   │               │      ▼  size stable 2s                  │
└──────────────────────┘               │ validate → sha256 → copy into ./processing │
                                       │      ▼  <intake_dir>/processing          │
                                       │ M17 scan_package: pyzbar + PaddleOCR +    │
                                       │     ExpiryParser + local catalog lookup  │
                                       │      ▼  candidate (READ-ONLY)            │
                                       │      └▶ /app/receive → human confirms    │
                                       │            (atomic batch + inventory)    │
                                       └─────────────────────────────────────────┘
```

Binding rules (identical to M17, carried over unchanged):

- **No mutation before confirmation.** The watcher only *scans*; committing stays
  on `POST /api/batch-intake/confirm` with human-entered quantity.
- **Barcode = identity only** — product lookup, never auto-creation.
- **OCR is always a candidate**, never verified truth.
- **No double-receive**: an identical photo (same content hash) is detected as a
  duplicate and parked in `processed/` without creating a second review.
- **No images in PostgreSQL** — only small JSON job metadata on disk.
- Rejects unsupported extensions, files >15 MB, corrupt/partial copies, and a
  file whose size keeps changing (still being copied).

## Layout of the intake area

The root defaults to `backend/data/intake` (override with `STOREYE_INTAKE_DIR`):

| Path | Purpose |
|------|---------|
| `intake/` | **Drop photos here.** The watcher sweeps this folder every ~1 s. |
| `intake/processing/` | A file that is currently being scanned (also `PARKED` during the USB stability wait). |
| `intake/processed/` | Finished/duplicate originals. |
| `intake/failed/` | Rejected or unrecoverable files. |

> Tip: put `intake/` on your desktop or in the Dock for a visible "drop zone".

## Enable the watcher

```bash
cp .env.example backend/.env      # already done by setup.sh normally
./scripts/storeye restart         # watcher auto-starts with the backend
./scripts/storeye status
```

Config (all in `backend/.env`):

| Var | Default | Meaning |
|-----|---------|---------|
| `STOREYE_INTAKE_DIR` | `""` → `DATA_DIR/intake` | Root intake folder. |
| `INTAKE_MAX_MB` | `15` | Max accepted file size (matches M17 gate). |
| `INTAKE_STABILITY_SECONDS` | `2.0` | Wait for a file's size to stop changing before scanning. |
| `INTAKE_WATCH_INTERVAL_SECONDS` | `1.0` | Watcher sweep interval. |
| `INTAKE_RETENTION_DAYS` | `7` | Auto-prune finished/rejected jobs older than N days (never active reviews). |

Check it is live on the **Smart Batch Receiving** page — a "Mobile Capture ·
USB intake" card shows the watcher state, intake path, counters and any
waiting candidates.

## Using it

1. On the phone camera, photograph the pack **flat, well-lit, filling the
   frame** (same rules as the in-browser capture).
2. Cable the phone to the edge node and **copy the photo** into `intake/`
   (drag out of the phone's DCIM/Photos — do not delete from the phone yet).
3. Within ~2–5 s the card shows the file; a few seconds later the real pipeline
   has produced a candidate (`REVIEW_REQUIRED`).
4. On the **Smart Batch Receiving** screen click **Review candidate** — the
   candidate prefills the existing review form in the browser. Edit if needed,
   type the quantity, **Confirm receipt** (one atomic transaction).
5. After confirmation click **Clear active job** and recycle: unplug the phone,
   delete the photo from the intake folder (processed copies stay in
   `processed/` until the 7-day sweep).

### Demo mode

Activate the **`MOBILE_USB_RECEIVING`** scenario (Demo view), then click
**Queue demo package** on the intake card. Two seeded catalogue packs are
available from the picker:

| Pack | Slug | Barcode | Batch |
|------|------|---------|-------|
| Aashirvaad Atta 5kg (₹240) | `aashirvaad` (default) | `8901063001015` | `M25-DEMO-01` |
| Amul Milk 1L (₹62) | `amul` | `8901262030003` | `M25-DEMO-02` |

Each is a watermarked `DEMO - NOT A REAL PHOTO` package dropped into the intake
folder through the same file watcher as a real USB copy, decoded by the same
real zbar + PaddleOCR + ExpiryParser, and must go through the usual human
review + confirm. Demo packages (filenames starting `storeye-demo-`) are always
cleared on `demo-reset`.

> In **production mode** (`DEMO_MODE=false`) the demo queue endpoint is
> disabled and demo packages never reproduce — same guard as all demo
> mutations.

## Failure semantics

| Symptom | Treatment |
|---------|-----------|
| Vitals never stabilise (still copied) | Left in `processing/` as `WAITING_FOR_COPY`; re-scans later. |
| Unsupported type / too large / corrupt | File `failed/`, job `FAILED` with a reason. |
| Scan pipeline error (OCR unavailable, etc.) | Job `FAILED` with the error; **Rescan** retries from the stored copy. |
| Identical already-mid-review photo | `PROCESSED` with `duplicate_of` — never a second review. |
| Identical to a previously *failed* photo | `FAILED` `DUPLICATE_OF_FAILED`, not reprocessed. |

Operator recovery: `POST /api/mobile-intake/jobs/{id}/rescan` retries a failed
job; `POST /api/mobile-intake/jobs/{id}/close` discards/archives a review.
`demo-reset` removes demo (and only demo) intake artifacts.

## API (read-mostly)

| Endpoint | Purpose |
|----------|---------|
| `GET  /api/mobile-intake/status` | Watcher state + counters + watch path. |
| `GET  /api/mobile-intake/jobs` | Job list (newest first). |
| `GET  /api/mobile-intake/jobs/{id}` | Single job + rehydrated candidate. |
| `POST /api/mobile-intake/jobs/{id}/close` | Mark a review job as handled (`PROCESSED`). |
| `POST /api/mobile-intake/jobs/{id}/rescan` | Retry a failed job from its stored copy. |
| `POST /api/mobile-intake/demo-queue` | [demo mode only, `X-Demo-Reset-Key`] Queue a watermarked demo package; optional JSON body `{"product":"amul"}` selects the pack (default `aashirvaad`). |

Confirmation is **not** here — it stays `POST /api/batch-intake/confirm` (M17).

## Why not "point the CCTV OCR at par below the counter"?

M17/M13 established the rule this reuses: reading printed `EXP/MFG/BATCH/MRP`
from a distance is not dependable. A close-up, appraisal-by-the-shopkeeper
photo is. The USB bridge simply delivers those close-ups **without a browser on
the edge machine** — same capture standard, same pipeline, same honesty.
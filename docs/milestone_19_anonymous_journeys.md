# Milestone 19 — Anonymous Multi-Camera Re-ID + Customer Journeys

**Date:** 2026-09-16
**Status:** ✅ Implemented and verified

---

## Summary

Up to M18, cameras tracked people with **per-camera ByteTrack ids only**: camera `c1`
saw "track 3", camera `c2` saw "track 7", and the system had no way to know both
were the same shopper. M19 adds **anonymous person re-identification (Re-ID) and
journey analytics** that stitch a shopper's path across the store — without ever
learning who they are.

```
camera A                        camera B
per-frame YOLO11n+ByteTrack ─┐  per-frame YOLO11n+ByteTrack ─┐
                             ▼                               ▼
   Re-ID crop+embed  ──▶ GlobalIdentityManager ──▶ Re-ID crop+embed
                          (appearance + time + camera graph)
                             │
                             ▼
   opaque global_person_id  (HIGH/MEDIUM/LOW/UNKNOWN)
                             │
              TRACK_ASSOC / ZONE_ENTER / ZONE_EXIT events
                             │
                             ▼
              ObservationWriter → PostgreSQL (journeys tables)
                             │
                             ▼
   GET /api/journeys · /api/journeys/summary · /api/journeys/{gid}
   GET /api/zones/{id}/analytics        →  React Journeys dashboard
```

**YOLO11n + ByteTrack are untouched.** They remain the per-camera detector/tracker.
Re-ID is a new upstream stage that only adds an opaque global id per person, and
every stage is **fail-graceful**: if the embedder is unavailable the pipeline emits
plain person events exactly as before.

## Old assumption vs new path

| Aspect | Before M19 | After M19 |
|---|---|---|
| Person identity | per-camera local track id only | local track id **+** anonymous `global_person_id` |
| Cross-camera continuity | none | appearance Re-ID + time gap + camera transition graph |
| Zoning | shelves only | named zones with foot-point enter/exit + dwell |
| What's shown to the user | "3 people tracked on c1" | "one anonymous shopper visited Entrance → Snacks → Billing in 9m 12s" |
| Privacy | detections only | still detections only — ids are opaque hashes, no names/faces/embeddings |

## Privacy rules (hard, encoded in the architecture)

- Every API key is an **opaque `global_person_id`** — a derived id, never returned
  as a person's name, face, or biometric.
- **Embeddings/image crops are never persisted** — they live in the edge runtime's
  memory only (`GlobalIdentityManager`), are compared in-place, then discarded.
- Journey API responses carry **no embeddings, no crops, no biometrics** (only ids,
  timestamps, camera/zone names, confidence buckets, durations).
- The provider only ever runs on-device/on-node from a cached weights file; it
  never initiates a download and no cloud service is contacted.
- Same-camera tracks never merge; false merges are considered worse than missed
  matches (threshold tuned conservatively, `REID_SIMILARITY_THRESHOLD=0.72`).

## Similarity + association math

`combined = cosine(appearance_embedding) × time_factor`

- appearance: L2-normalised ResNet18 penultimate features (512-d) for the real
  provider, deterministic hash for the stub.
- time factor: linear decay `1.0 → 0.45` from gap 0 up to `REID_MAX_TIME_GAP_SECONDS=120s`.
- camera graph: a transition candidate is only considered between cameras linked
  via `next_cameras` (default: open — any camera may precede any other).
- score map: **HIGH ≥ 0.86**, **MEDIUM ≥ 0.72**, **LOW > 0**, **UNKNOWN** = new identity.
- store key: `(store_id, global_person_id)`; identity expires after
  `GLOBAL_PERSON_TIMEOUT_SECONDS=1800s` — a re-sighting afterwards starts a new journey.

## Edge integration

- `EdgePipeline` crops each tracked person on a throttle (new track → embed now;
  refresh cadence 10 s) and feeds `PersonSighting`s into the shared, store-scoped
  `GlobalIdentityManager`.
- On match the person event carries `global_person_id` + `reid_confidence`, and the
  pipeline emits `TRACK_ASSOC`, `ZONE_ENTER`, `ZONE_EXIT` journey events.
- `ObservationWriter` (now given a `JourneyService`) persists those rows; PERSON
  observation `details` are enriched with `global_person_id` / `reid_confidence` / `zone_id`.
- Camera config parses optional `zone_id`, `zones` (foot-point bboxes), `next_cameras`,
  and `reid`; `set_store` runs before `add_camera` so journeys are store-scoped.

## Config (settings)

| Setting | Default | Purpose |
|---|---|---|
| `REID_ENABLED` | `True` | master switch |
| `REID_PROVIDER` | `torch` | `torch` / `openvino` / `stub` |
| `REID_SIMILARITY_THRESHOLD` | `0.72` | MEDIUM starting score |
| `REID_HIGH_CONFIDENCE_SCORE` | `0.86` | HIGH starting score |
| `REID_MAX_TIME_GAP_SECONDS` | `120.0` | max inter-camera gap |
| `GLOBAL_PERSON_TIMEOUT_SECONDS` | `1800.0` | session expiry → new journey |
| `REID_UPDATE_INTERVAL_SECONDS` | `10.0` | stable-track re-embed cadence |

## API

- `GET /api/journeys?store_id=` — paged journeys (filters: camera, zone, time, confidence)
- `GET /api/journeys/summary?store_id=` — total/active visitors, avg duration/dwell, most-visited zone
- `GET /api/journeys/{global_person_id}?store_id=` — full timeline, track associations, zone visits, transitions
- `GET /api/zones/{zone_id}/analytics` — visits, unique visitors, dwell percentiles, currently inside

## Database

Four new tables (alembic `d96754c9650a`):

- `globalPersonSessions` — one row per `(store_id, global_person_id)` journey
- `personTrackAssociations` — local camera track → global person, per camera
- `zoneVisits` — one enter/exit per person per zone (dwell computed on exit)
- `zoneTransitions` — inter-camera graph edges observed per person

`seed_demo.py` seeds 5 zones, 5 cameras (incl. a new aisle camera), and 4 demo
journeys (alice HIGH multi-camera active, bob UNKNOWN expired, carol MEDIUM billing
dwell, dave LOW active); `--reset` clears the journey tables too.

## Verification

- `tests/test_journeys.py` — 18 unit tests, scenarios A–N + confidence mapping.
- `tests/test_journeys_api.py` — list/summary/detail/404, zone analytics, camera config validation (bad zone bbox → 422).
- `tests/test_journeys_edge.py` — pipeline emits TRACK_ASSOC/ZONE enter-exit; writer persists journeys; PERSON details enriched.
- `tests/test_reid_real_ai.py` — opt-in `real_ai` smoke: real cached ResNet18 → 512-d L2-normalised embedding + latency.
- Backend full suite: **246 passed** (PostgreSQL, `alembic check` clean). Frontend: **96 passed**, typecheck + build green.

**Measured on this Mac (cached `resnet18` weights): torch encode ≈ 13.3 ms / crop,
stub ≈ 0.117 ms — both well inside the edge worker's 0.5 s frame budget.**

## Non-goals / stop boundary

- No identity database, no face recognition, no biometrics, no cloud APIs.
- No single-camera "lost-then-found" behavior changes: ByteTrack track ids are
  preserved per camera; Re-ID only adds a cross-camera layer.
- M20 (upsell / loyalty / individual basket attribution) is **out of scope** and
  explicitly NOT started — this milestone stops at anonymous journey analytics.
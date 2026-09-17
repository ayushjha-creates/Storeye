# Storeye — Privacy Architecture

Storeye is a privacy-first, offline-first edge platform. This document states
the guarantees, where they are enforced in code, and how they are tested.

## 1. Principles

1. **No identity.** Storeye never knows who a person is.
2. **No biometrics.** No face recognition, no face embeddings, no demographic
   inference, no fingerprint/gait/voice.
3. **No raw media in the database.** Video frames and images are processed in
   process memory and discarded; PostgreSQL stores metadata/observations only.
4. **Anonymous, ephemeral continuity.** Cross-camera Re-ID uses in-memory
   embeddings and opaque ids that never leave the process and never identify a
   person across sessions.
5. **Data minimisation.** Only what a retail decision needs is stored.
6. **Human-in-the-loop.** AI produces observations/advisories; business records
   change only through explicit human-confirmed operations.

## 2. Where each guarantee is enforced

| Guarantee | Enforcement |
|-----------|-------------|
| Person observations are anonymous | `app/models/observation.py` — `track_id` is an opaque, session-scoped integer; no name/face/identity columns. |
| Cross-camera continuity is anonymous | `app/models/journeys.py` — `global_person_id` is an opaque, store-scoped string mapped only to camera-local track ids. |
| Re-ID embeddings are not persisted | Re-ID lives in process memory (`app/edge/reid/`); there is no embedding column anywhere. |
| Raw frames/video are not persisted | Observations store bbox/text/metadata JSONB only; `source` is a path/label, never media bytes. |
| OCR results are not business truth | `app/services/batch_intake/` requires explicit human confirmation before any batch/inventory write. |
| Insights/alerts store evidence only | `app/models/insight.py`, `app/models/alert.py` — JSONB evidence/metadata; explicitly never images or embeddings. |
| No media/biometric columns exist | `IntegrityCheckService.check_privacy()` fails the build/runtime if any image/embedding/face/biometric/thumbnail/video column appears in observation, journey, alert or insight tables. |
| Identity expires | `GLOBAL_PERSON_TIMEOUT_SECONDS` (default 1800 s) starts a new anonymous session after idle; `REID_MAX_TIME_GAP_SECONDS` (default 120 s) bounds association. |

## 3. Re-ID data flow

```
camera frame ──▶ person detector ──▶ local track_id (per camera)
                        │
                        ▼
              embedding (in memory only, resnet18 / OMZ by config)
                        │  cosine/gated match within REID_MAX_TIME_GAP_SECONDS
                        ▼
        global_person_id (opaque) ──▶ zone_visits / transitions (metadata only)
                        │
                        ▼
        in-memory identity forgotten after GLOBAL_PERSON_TIMEOUT_SECONDS
```

Nothing in this pipeline writes an embedding, image, or identity to disk or to
PostgreSQL. Disabling Re-ID (`REID_ENABLED=false`) leaves the platform fully
functional: only camera-local track ids remain, and journeys degrade gracefully.

## 4. AI as advisory only

- `app/models/observation.py` states the rule: *AI observation != business
  truth*. Recording an observation never changes inventory or creates batches.
- Shelf/product intelligence and Store Intelligence (M20) are deterministic,
  rule-based, and read-only over existing rows. Their only side effect is an
  M16 alert via the single `AlertService` dedup path.
- Smart Receiving (M17) requires a human to confirm parsed batch/expiry data
  before it is committed; images are used transiently and discarded.

## 5. Offline-first and data locality

- The entire operational loop runs locally (PostgreSQL + FastAPI + browser). No
  cloud service is required or used.
- Internet loss is normal and explicitly surfaced as advisory, not an error.
- There is no operational write-back to any external system in scope.

## 6. What Storeye does *not* claim

- Storeye is **not** a biometric system and must not be extended into one.
- Storeye does **not** provide authentication. It is intended for a trusted,
  single-tenant edge deployment on a local network. Deployers who expose it
  beyond localhost/trusted LAN must add a reverse proxy with authentication and
  TLS (see `docs/deployment.md`).

## 7. Verification

```bash
# Structural privacy assertion (no media/biometric columns)
DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye" \
  ./backend/.venv/bin/python -m scripts.integrity_check --json   # from backend/
```

Tested by:
- `backend/tests/test_observations.py` — anonymous track ids, no identity.
- `backend/tests/test_journeys.py` / `test_journeys_edge.py` — anonymised
  journeys; embeddings never persisted.
- `backend/tests/test_integrity_check.py::test_privacy_check_passes_on_real_schema`.
- `backend/tests/test_reid_real_ai.py` — real Re-ID pipeline (in-memory).

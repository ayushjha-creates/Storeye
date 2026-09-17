# Milestone 21 — Storeye Demo & Scenario Engine

## Summary

M21 turns the single static M18 showcase dataset into a **deterministic scenario
engine**: the presenter can switch the demo store between 12 realistic retail
situations, and every switch is applied by the **real backend** to the **real
database** and re-evaluated through the real M20 insight / M16 alert pipeline.
Nothing is a mock, a recorded fixture or frontend-only state — reloading the
browser keeps the active scenario.

This is exactly the SIH-style story: one store, one command, the *whole* product
(observations → intelligence → insights → alerts → actions) visibly reacting,
offline and without any cloud/LLM/CV model.

## Hard constraints (encoded, tested)

- **Demo store only.** The engine resolves `DEMO_STORE_ID` and refuses unless
  `Store.is_demo is True`; the guard lives in the service layer (not just HTTP),
  so a non-demo store can never be modified. A dedicated test proves a
  production store's inventory, insights and alerts are untouched.
- **DB-backed scenarios.** `demo_scenario_state` persists the active key; a page
  refresh re-reads it. No scenario is stored in React/browser state.
- **Reset-first, then overlay.** Every activation starts from the identical
  seeded baseline, so scenarios never contaminate one another and the same key
  twice yields the same state (deterministic; asserted by test).
- **Deterministic.** Fixed UUIDs (`fixed()`), fixed observation plans, fixed
  visit counts, no randomness, no wall-clock dependence in the overlay (the
  engine takes an explicit `now`).
- **Reuse, don't duplicate.** Scenarios write domain rows (inventory, batches,
  observations, zone visits) and then call the existing `InsightEngine`; there is
  no parallel intelligence path.
- **No auto-mutation by intelligence.** The M20 engine still never changes stock
  (proven in M20's no-mutation tests). Scenarios are the only writers, and they
  write demo data on purpose.
- **No new model / LLM / cloud / CV.** Smart Receiving deliberately runs the REAL
  M17 close-up scan workflow (barcode + OCR + human confirmation) — no OCR is
  faked.
- **Privacy.** People flow stays aggregate (zone visits) and is never translated
  into intent.

## Scenario catalog

| Key | Category | What it exercises |
|---|---|---|
| `NORMAL_STORE` | healthy | HEALTHY baseline; default state |
| `LOW_STOCK` | inventory | `LOW_STOCK` (MEDIUM) + high-selling-low-stock |
| `OUT_OF_STOCK` | inventory | `OUT_OF_STOCK` (HIGH) + SHORTAGE alert |
| `EXPIRY_RISK` | expiry | `EXPIRY_RISK` (MEDIUM) + `EXPIRED_BATCH` (HIGH) |
| `LOW_SHELF_BACKSTOCK` | shelf | `LOW_SHELF_AVAILABILITY` while inventory is available |
| `MISPLACEMENT` | shelf | possible misplacement (never stated as certainty) |
| `HIGH_TRAFFIC` | customer_flow | `HIGH_TRAFFIC_ZONE` (INFO) from zone visits |
| `HIGH_DWELL` | customer_flow | `HIGH_DWELL_ZONE` (INFO) from dwell |
| `MULTI_CAMERA_JOURNEY` | customer_flow | one anonymous person across ≥3 cameras |
| `CAMERA_OFFLINE` | camera | `CAMERA_HEALTH` (HIGH) + CAMERA_OFFLINE alert |
| `SMART_RECEIVING` | receiving | healthy baseline for the real M17 scan flow |
| `COMBINED_CRISIS` | crisis | many problems + many alerts at once |

`DEFAULT_SCENARIO = NORMAL_STORE`. The catalog is pure metadata in
`app/services/demo/demo_data.py` (no DB access) so schemas, routers and the
frontend contract share it.

## Engine flow

`DemoScenarioEngine.activate(key, now)`:

1. `_require_demo_store(create=True)` — resolve + guard.
2. `reset_to_baseline()` — full M18 re-seed (separately committed).
3. Overlay `APPLIERS[key](session, store, now)` — mutate only demo-store rows.
4. `InsightEngine.evaluate(store.id, now, reference_date)` — one atomic
   reconcile that writes rule insights, the cached `STORE_HEALTH` summary and
   M16 alert sync.
5. Persist `demo_scenario_state` (`active_key`, timestamps) and commit.

On any failure: rollback, best-effort re-seed the baseline, reset state to
`NORMAL_STORE`, and re-raise — a presenter is never left with a half-modified
store. `reset()` is simply `activate(NORMAL_STORE)`.

`_neutralize()` is the shared "heal the rich baseline" step: stock pushed above
reorder levels, batch expiries far in the future, a neutral on-planogram shelf
observation plan, fresh per-camera heartbeats, and derived alerts/insights
cleared. Scenarios then inject their specific problem. `COMBINED_CRISIS` skips
neutralisation and keeps the rich M18 baseline.

### M20 correction

The M20 module docstring already promised that `evaluate()` persists the cached
`STORE_HEALTH` summary in the same cycle, but the candidate was missing — so the
cached row was never written by `evaluate()`, and the separate
`evaluate_store_health()` call resolved every sibling insight (a reconcile with a
single candidate). M21 fixes this: the store-health candidate is appended inside
`evaluate()`, so one cycle persists everything and retires nothing incorrectly.
The canonical seed therefore reports **22 insights** (was 21) and three M20 API
count assertions were updated accordingly.

## Isolation & guard

- `Store.is_demo` — new boolean column (default false, indexed), set by the
  seeder; migration backfills `Storeye Demo Mart`.
- `DemoScenarioState` — one row per demo store (FK cascade): `active_key`,
  `last_reset_at`, `last_activated_at`.
- `DEMO_STORE_ID = fixed("store")` (stable uuid5) — the engine targets this id,
  never "the first store".
- Errors: `DemoStoreNotFound` → 503, `NotADemoStore` → 403, `UnknownScenario` →
  404.

## API surface

| Endpoint | Guard | Purpose |
|---|---|---|
| `GET /api/demo/scenarios` | demo mode | catalog + active key |
| `GET /api/demo/scenarios/{key}` | demo mode | one scenario (404 unknown) |
| `GET /api/demo/status` | demo mode | active scenario, store id/flag, timestamps |
| `POST /api/demo/scenarios/{key}/activate` | `X-Demo-Reset-Key` | apply scenario + re-evaluate |
| `POST /api/demo/reset` | `X-Demo-Reset-Key` | reset to `NORMAL_STORE` |

`DEMO_MODE` (default true) 404s the whole surface when off. There is still **no
auth system** in the codebase; the reset key is the pragmatic guard and the
isolation guarantee is the service-layer `is_demo` check. Documented limitation.

## Frontend

- **Demo Control Center** (`/app/demo`, new nav item "Demo Control"): active
  scenario banner (description + deep link to the affected view), the 12-card
  catalog with category badges, expected effects, per-card **Activate** (disabled
  while active), **Reset to Normal**, and a **Presentation mode** toggle. After
  each activation it re-reads status and shows the evaluation summary
  (created/refreshed/resolved insights, alerts).
- **Presentation hub** (`/app/demo/presentation`): the single screen a presenter
  keeps open — current scenario, "what is happening" (expected outcomes) and
  direct links to the REAL pages: Dashboard, Live Store, Inventory, Alerts,
  Journeys, Smart Receiving, Insights. No animations or mock content.
- **Persistent demo badge**: a subtle "Demo store" pill in the app-shell top bar,
  shown only when the backend reports `store_is_demo`, so demo vs production can
  never be confused.
- **Presentation mode**: a persisted per-browser preference
  (`src/lib/demo/presentation.ts`) that renders a global `DemoBanner` in the app
  shell — active scenario name, quick Reset, Control-center link and Exit.
- **Dashboard**: a "Showcase Scenario" card showing the active scenario and a
  link to the control center; degrades to an empty state when demo mode is off.
- New `demoApi` module + typed mirror (`src/lib/api/demo.ts`, `types.ts`),
  `IconPlay`. The API client now supports per-request headers for the guarded
  calls.

## Demo data

`scripts/seed_demo.py` marks the store `is_demo=True` and ends with
`InsightEngine.evaluate`, so the baseline includes the cached `STORE_HEALTH`
summary. Canonical seed: **22 insights**, 8 alerts, 5 insight→alert syncs, 234
observations. `reset_demo_store` clears insights (and, via FK cascade, the
scenario state). Seeding stays idempotent.

## 5-minute demo flow

1. **Sign in** with the showcase account → healthy `NORMAL_STORE`; Dashboard
   shows all KPIs and a HEALTHY store.
2. **Demo Control Center** → activate **Low Stock** → Insights page shows
   `LOW_STOCK` with evidence + recommended action; store health ATTENTION.
3. Activate **Expiry Risk** → expiry insights and alerts appear; show the
   evidence modal (batch numbers, days-to-expiry) and the human-reviewed action.
4. Activate **Camera Offline** → `CAMERA_HEALTH` (HIGH) + alert; Live Store /
   Cameras shows the stale camera while the rest report.
5. Activate **Multi-Camera Journey** → one anonymous global person across 3
   cameras (no face/embedding).
6. Activate **Smart Receiving** → run the real M17 scan → human confirm → stock
   moves atomically.
7. Activate **Combined Crisis** → many insights/alerts at once → Alerts Center,
   then **Reset to Normal** to end clean.

## Verification

- **Backend (PostgreSQL)**: `tests/test_demo_scenarios.py` (21 engine/rule/
  determinism/isolation tests) + `tests/test_demo_api.py` (10 HTTP tests) →
  **329 passed** overall, `alembic check` clean, head `19c835a1a344`. SQL smoke
  over all 12 keys confirmed the expected insight/alert surface and store-health
  state.
- **Frontend**: `npx tsc -b` clean, `npx vitest run` **114 passed** (5 for
  `DemoControlCenter`, 3 for `DemoPresentation`), `npm run build` green.
- Production-store isolation, guard errors, reset determinism and scenario
  non-inheritance are all covered by tests.

## Performance (measured, local PostgreSQL + uvicorn)

Median of repeated calls on the demo store (reset ≈ activation, since every
activation resets first):

| Operation | Median |
|---|---|
| `GET /api/demo/status` | ~2 ms |
| `GET /api/demo/scenarios` | ~2 ms |
| `GET /api/insights/summary` (dashboard) | ~2 ms |
| `POST /api/demo/reset` | ~468 ms |
| Activate `LOW_STOCK` | ~473 ms |
| Activate `LOW_SHELF_BACKSTOCK` | ~464 ms |
| Activate `CAMERA_OFFLINE` | ~525 ms |
| Activate `COMBINED_CRISIS` | ~583 ms |

Reads are sub-3 ms; a full reset+overlay+insight+alert cycle is under 0.6 s, so
scenario switches are comfortable for a live presentation. No model runs during
activation (observations are data, not inference), so there is no training or
warm-up wait.

## Privacy recap

Scenarios add only aggregate zone visits and deterministic on-shelf product
observations. No faces, crops, embeddings or identity are created or exposed;
multi-camera journeys remain anonymous.

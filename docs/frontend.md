# EdgeRetail-IQ Frontend

Milestone 12 adds the web frontend that turns the FastAPI domain API into a
usable, offline-first storekeeper UI. It is a plain **Vite + React 18 +
TypeScript** SPA served by Vite locally — no Next.js, no Supabase, no cloud
deployment. PostgreSQL (via FastAPI) is the single source of truth.

## Stack

- Vite 5 + React 18 + TypeScript (strict) + Tailwind CSS.
- `react-router-dom` v6 for routing.
- All data access through `src/lib/api/*` modules backed by `client.ts`
  (`fetch` wrapper with timeout, auth header hook, friendly error mapping).
- Unit/component tests with **Vitest + jsdom + Testing Library**(`npm test`).

## Running

Frontend proxies `/api` to `http://localhost:8000` (see `vite.config.ts`).

```bash
# Terminal 1 — backend (from backend/)
export DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye"
.venv/bin/uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend (from frontend/)
npm install
npm run dev        # http://localhost:5173

# Tests / typecheck / build (from frontend/)
npm test           # vitest run (40 tests)
npm run build      # tsc -b && vite build
```

## Auth model (Milestone 12)

There is **no backend authentication yet** (see the note in `docs/api.md`).
The frontend ships a local UI-auth foundation:

- `AuthProvider` keeps a session in `localStorage` (`storeye.auth.session`).
- "Login" verifies the Edge Hub is reachable (`GET /api/health`); reachability
  is the only gate — it is **not** a real credential check.
- `ProtectedRoute` guards the shell; signed-out users land on `/login`.
- `setAuthToken()` is available for M13+ to attach `Authorization: Bearer`
  without changing call sites.

Practical consequence: the login screen grants no backend security. It exists
so the UI works today and a real auth middleware can be dropped in later.

## Edge-first / offline-first behavior

EDGE ONLINE + INTERNET OFFLINE is the normal operating condition.

- The whole app talks only to the local FastAPI Edge Hub; there is no cloud.
- `EdgeProvider` polls `/api/health`; `OfflineBanner` and `EdgeNodeStatus`
  reflect `edgeOnline` / `engineStatus` / `internetOnline`.
- Every page degrades gracefully: unknown network failures render an
  edge-unreachable message, domain errors render their `detail` message, and
  already-loaded data stays visible.
- Verified live: the SPA keeps serving with the backend stopped; API calls
  fail into the offline/degraded UI states. Postgres remains the source of
  truth — the DB is never bypassed from the browser.

## Pages

| Route | Page | Purpose |
|-------|------|---------|
| `/` | Dashboard | store KPIs, AI runtime, low-stock watch, recent AI observations |
| `/cameras` | Cameras | camera list with per-camera latest observation |
| `/cameras/:cameraId` | CameraDetail | stream + detection overlay + analysis + observation timeline |
| `/observations` | Observations | filterable AI observation timeline |
| `/reconciliation` | Reconciliation | run/summarize shelf reconciliation (informational) |
| `/inventory` | Inventory | stock per product, batches, movements; receive/adjust/create-batch |
| `/billing` | Billing | manual cart-based bill creation (POS-integrated, see below) |
| `/products`, `/customers` | Products / Customers | CRUD |
| `/settings` | Settings | connection + session status |
| `*` | NotFound | 404 |

## Milestone 12 product rules (non-negotiable)

- **Billing is manual only.** A bill is built from a cart; no AI generates
  bills, and a bill never auto-changes inventory.
- **AI is informational only.** Observations and reconciliation results
  never auto-mutate inventory; the human approves every stock change.
- **Video stays on the edge.** Cameras never upload video. The live-stream
  endpoint does not exist yet, so `CameraStream` renders an explicit
  "stream unavailable" state with abstracted `mjpeg/hls/video` config support.
- **Anonymous detections only.** No face recognition.

## Layout & testing

- `src/components/` — UI kit (`ui/`), layout (`layout/`), camera widgets
  (`camera/`: `CameraStream`, `DetectionOverlay`, `AnalysisPanel`,
  `ObservationTimeline`), `EdgeNodeStatus`, `OfflineBanner`.
- `src/pages/` — one file per route (named exports `*Page`).
- `src/test/` — Vitest setup + `stubFetchRoutes` mock helper (URL-substring
  route table; list specific keys before generic ones).
- Money/tax fields are serialized as strings (Postgres Decimal); send string
  payloads, convert with `Number(...)` for display. `tax_rate` is a fraction
  (`0.18` = 18%); display with `* 100`.

Running `npm test` (40 tests) and `npm run build` (strict `tsc`) must stay
green before any M12+ change is considered done.
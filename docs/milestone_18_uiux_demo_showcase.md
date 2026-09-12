# Milestone 18 — UI/UX Rebrand + Demo Showcase Mode

**Date:** 2026-09-09
**Status:** ✅ Implemented and verified

---

## Summary

M18 closes the product off in two ways:

1. **A deterministic, clearly-labelled demo dataset** ("Storeye Demo Mart") that a
   visitor can explore end-to-end — products, shelves, cameras, 192 product + 42
   person AI observations, planogram, batch stock, alerts, reconciliation
   snapshots and 7 days of billing/sales — all synthetic, all safely re-creatable.
2. **A cohesive enterprise-SaaS light UI** on the existing offline-first stack:
   navy `brand` palette + gold accent, a dedicated icon set and dependency-free
   SVG charts, a full shell redesign (10 primary + 5 reference nav items) and new
   **Live Store** and **Reports & Analytics** pages. Existing APIs, routes,
   data-flows and M1–M17 guarantees are untouched.

No new runtime dependency was added. Everything remains local and offline-first.

## Demo dataset (backend)

`backend/scripts/seed_demo.py` seeds the full showcase in one command:

```bash
cd backend
.venv/bin/python -m scripts.seed_demo          # create demo store
.venv/bin/python -m scripts.seed_demo --reset  # wipe + re-create, identical
```

Design rules:

- **Deterministic:** every record uses `fixed(slug) = uuid5(NAMESPACE_URL,
  "storeye-demo/" + slug)`, so UUIDS are stable across runs and machines (no
  per-load randomness).
- **Idempotent:** re-running creates **zero** new batches/alerts/sales — the store
  converges to exactly 234 observations (192 PRODUCT + 42 PERSON).
- **Dated realistically:** customer purchases are back-dated over 7 days while
  observations, alerts, AI runtime and room scenes stay "today"-relative, so a
  demo looks alive on any day.

Store summary (verified against the dev DB via the real services):

| Area | Demo values |
|------|-------------|
| Store | Storeye Demo Mart · New Delhi · Asia/Kolkata · 011-4012-3456 |
| Manager | Rohan Verma (mobile 9811000000, role *Store Manager*) |
| Customers | Ananya Gupta, Rahul Mehta |
| Zones/Shelves | Snacks, Beverages; shelves A1, A2, B1, B2, E1 |
| Products | 14 SKUs (Aashirvaad Atta, Tata Salt, Amul Milk, Parle-G, Fortune Oil, Maggi, Surf, Coke, Pepsi, Fortune Rice, Amul Butter, Nescafé, Dairy Milk, …) |
| Batches | Amul Milk (3 lots incl. an expired 2026-08-20), Aashirvaad (60 bags, exp 2026-10-05), Fortune (2 lots) |
| Cameras | Demo Shelf / Entrance / Till / Roof (Roof has no observations → `ai_stopped`) — 3 running, 1 stopped |
| Shelf regions | 5 non-overlapping strips mapped to A1/A2/B1/B2/E1 |
| Planogram | A1=[Aashirvaad, Parle-G], A2=[Maggi], B1=[Tata Salt, Fortune, Coke], B2=[Amul Milk, Coke] |
| Intelligence | Tata Salt POSSIBLE_SURPLUS (72/60), Fortune MATCH, Amul Milk MATCH, Parle-G MATCH, Maggi MATCH (10), Aashirvaad POSSIBLE_SHORTAGE (8/60), Pepsi NO_INVENTORY, PremiumDetergent NOT_ASSESSED; shelves A1 NORMAL 100%, A2 LOW, B1 NORMAL, B2 NORMAL 81%, E1 EMPTY; 1 misplacement (Maggi@B2) |
| Alerts | 8: 6 OPEN (shortage/expired/soon/MISPLACEMENT/low-shelf/offline), 1 ACKNOWLEDGED (surplus), 1 RESOLVED |
| Recon snapshots | AAS SHORTAGE (60/8), TATA SURPLUS (60/72), PARLE MATCH (18), MAGGI REVIEW (10, conf 0.62) |
| Sales | 7 days; today ≈ 186 pcs / ₹24,918; bills DEMO-BILL-0001..0007 DELIVERED |

Sales intentionally do **not** touch inventory — consistent with the backend
(commerce never mutates stock; receiving does).

## Demo reset endpoint

`POST /api/demo/reset` (router `backend/app/api/routers/demo.py`, registered in
`app/api/routers/__init__.py` + `app/main.py`). Guarded by the `X-Demo-Reset-Key`
header (server-side env `DEMO_RESET_KEY`, default `storeye-demo-reset` for dev).
Wrong/missing key → **403**; correct key → deletes the demo store's data and
re-seeds it idempotently.

## Frontend design system

`frontend/tailwind.config.js` now defines a complete palette + fonts:

- **brand** = navy/blue scale (900 `#1E2A5A`, 950 `#152047`, …) — replaces the old
  green `brand` tokens; **gold** accent (`#F5B92E` / `#D99A12`) for demo/emphasis;
  built-in **emerald/amber/red** remain the semantic ok/warn/critical colors.
- `frontend/src/index.css` adds base typography and helpers:
  `.page-shell`, `.card`, `.table-base`, `.demo-badge`, `.tabular`, scrollbars.
- `frontend/src/components/ui/icons.tsx` — hand-rolled SVG icons (no icon dep).
- `frontend/src/components/ui/charts.tsx` — `LineChart`, `BarChart`, `DonutChart`,
  `Sparkline`, `MiniProgress` (pure SVG; no chart dep).
- `frontend/src/config/demo.ts` — env-backed demo config (defaults:
  `demo@storeye.local` / `StoreyeDemo@123`, demo store name, dev-only reset key).

### Shell, login, dashboard

- **AppShell** redesigned: dark navy gradient sidebar with
  `Workspace` (10 items: Dashboard, Live Store, Product Intelligence, Shelf
  Intelligence, Alerts, Inventory, Smart Receiving, Billing, Reports & Analytics,
  Settings) and `Reference` (Products, Customers, Cameras, AI Observations,
  Reconciliation); top bar with search, edge-status pill, notification bell,
  user menu + logout; demo badge + store-name card when in demo mode; mobile
  drawer; cohesive footer.
- **Login** split-panel branding screen with a “Use demo account” pre-fill card
  (kept auth-limitation note + all previous behaviors/tests).
- **AuthContext** recognises the public demo credentials and marks the session
  `demo` (badge appears in shell + pages).
- **Dashboard** rebuilt: KPI icons + trend tints, 7-day sales `LineChart`, AI
  snapshot card, plus the existing observations / low-stock / smart-receiving /
  runtime / alerts / reconciliation cards. All test-asserted copy preserved.

### New pages

- **Live Store** (`/live-store`) — people-in-store, active cameras, regions with
  AI data, visible stock, a storefront shelf map (zones × shelves with occupancy
  progress + state badges + visible-product chips), camera rail and near-realtime
  detections; auto-refreshes every 30 s.
- **Reports & Analytics** (`/reports`) — 30-day KPI cards, 14-day revenue
  `LineChart`, top-products `BarChart`, recent-bills table. Everything derived
  from real sale/bill records (never hardcoded).

All remaining pages (Cameras, CameraDetail, Observations, Reconciliation,
Inventory, ReceiveSmart, Billing, Products, Customers, Settings, Alerts,
ProductIntelligence, ShelfIntelligence, NotFound) were re-skinned to the same
language. `CameraStream` live dot now uses `emerald-500` (semantic “ok/live”).

## Verification

- Frontend: `cd frontend && npx tsc -b` clean; `npx vitest run` → **78 passed**;
  `npm run build` clean. New tests: `LiveStore.test.tsx`, `Reports.test.tsx`.
- Backend: `TEST_DATABASE_URL='postgresql+psycopg2://storeye@localhost:5433/storeye_test'
  .venv/bin/python -m pytest tests/ -q` → **221 passed** (demo router covered).
- Demo seed idempotency: two consecutive `python -m scripts.seed_demo` runs add
  0 new batches/alerts/sales and keep exactly 234 observations in the demo store.

## Files created / modified (M18)

Backend:
- `backend/scripts/seed_demo.py` (new) — deterministic idempotent demo seed.
- `backend/app/api/routers/demo.py` (new) — guarded `POST /api/demo/reset`.
- `backend/app/api/routers/__init__.py`, `backend/app/main.py` — register router.

Frontend:
- `frontend/tailwind.config.js`, `frontend/src/index.css` — design tokens/helpers.
- `frontend/src/components/ui/icons.tsx`, `frontend/src/components/ui/charts.tsx` (new).
- `frontend/src/config/demo.ts` (new).
- `frontend/src/auth/AuthContext.tsx` — demo session marking.
- `frontend/src/pages/Login.tsx`, `frontend/src/pages/Dashboard.tsx` — rebuilt.
- `frontend/src/pages/LiveStore.tsx`, `frontend/src/pages/Reports.tsx` (new) + tests.
- `frontend/src/components/layout/AppShell.tsx` — full shell redesign.
- `frontend/src/pages/{Alerts,Billing,CameraDetail,Cameras,Inventory,Observations,ProductIntelligence,Reconciliation,ReceiveSmart,ShelfIntelligence,Products,Customers,Settings,NotFound}.tsx` — restyled.
- `frontend/src/components/camera/CameraStream.tsx` — semantic live dot.
- `frontend/public/storeye-logo.svg` — cleaned brand logo (C2PA metadata removed).

Docs:
- `docs/api.md` — demo reset endpoint notes.
- `docs/milestone_18_uiux_demo_showcase.md` (this file).
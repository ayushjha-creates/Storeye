# M28 — Shopkeeper-First Frontend Redesign + Footfall Graph

Status: **COMPLETE**. Backend 487 passed / frontend 153 passed, `npx tsc -b`
clean, `npm run build` green (116.90 kB gzip), `alembic check` clean.

Storeye stopped presenting itself as an "AI engineering console" and now reads
as a simple retail-management app. Nothing functionally was deleted — every
screen still exists — but the information architecture, navigation, and
language were rebuilt around what a shopkeeper does daily.

## What changed

### New navigation (§3–§6)
- **Sidebar** (desktop): two groups only —
  - **Workspace**: Home, Sales, Stock, Receive Stock, Alerts, Reports.
  - **Store operations**: Cameras, Settings (+ a small **Demo** entry only for
    the deterministic demo store).
- **Mobile bottom bar** (`<lg`): Home / Sales / Stock / Receive / Alerts, plus
  **More → Settings**. No long drawer.
- Header now shows the store name + a status pill ("Store running locally" /
  "Offline mode") instead of a search field and notification bell.
- All old routes are kept and resolve (`/app/inventory`, `/app/inventory/receive`,
  `/app/journeys`, `/app/insights`, `/app/demo`, …). New aliases added:
  `/app/sales`, `/app/stock`, `/app/receive`, `/app/dashboard`,
  `/app/settings/advanced`.

### Pages relocated (§4, §43)
Advanced / internal screens moved under **Settings → Advanced** (new
`SettingsAdvanced.tsx`, gated to MANAGER+ via `canManage`): Stock activity,
Shelf configuration, Product intelligence, AI diagnostics, Observations, Stock
check (reconciliation), Customer journeys, AI insights, Live store view.
`Settings.tsx` also gained store-tool tiles (Products, Customers, Cameras, Live
store) and a Demo tile (isDemo only).

### Dashboard → shopkeeper Home (§7–§8)
Answers "how much did I sell today / what stock do I have / what needs my
attention / what should I do next":

- Greeting + store + status header.
- KPI cards: Today's Sales (₹), Current Stock, Running Low, Expiring Soon,
  Today's Bills.
- **"What needs your attention"** — built from **real live APIs only**, never
  fabricated: out-of-stock / running-low / expired / expiring batches (inventory
  + batches), pending mobile-intake receipts, offline cameras (edge health),
  and shelves needing restock (intelligence summary). When there is nothing, it
  says so in green.
- Quick Actions: Receive Stock / New Sale / Check Stock / View Alerts.
- 7-day Sales line chart + **new 7-day Store Footfall bar chart** (from
  `GET /api/journeys/daily`, labelled "counted by your cameras").
- Store activity (customers today, products seen, shelves needing restock),
  a Cameras card, and recent stock receipts.

### Plain language (§35, §40)
New translation layer `frontend/src/lib/shop.ts`: `greeting`, `formatINR`,
`stockStatus` (Good / Running low / Out of stock), `expiryLabel`,
`alertCategory`, `alertTypeLabel`, `ALERT_SEVERITY_LABEL`,
`EMPTY_COPY`, `ERROR_COPY`, `errorMessage`.

- Alert severities now render as **Urgent / High / Medium / Low / Info**
  (`AlertSeverityBadge`) instead of leaking `CRITICAL`.
- Alert cards use `alertTypeLabel` ("Shelf needs restocking", "Running low")
  instead of internal enum names.
- Billing → **Sales**; Inventory → **Stock** (with All / Running low / Out of
  stock / Expiring soon filter tabs and Status + Expiry columns);
  ReceiveSmart → **Receive Stock** ("Scan with your phone"); Alerts →
  **Things that need attention** ("Check now"); Cameras → "Your cameras" +
  "Set up your first camera" + a Live-store link.

### Backend addition (§38, read-only)
`GET /api/journeys/daily?store_id=&days=` (default 7, 1..30) returns one row per
`GlobalPersonSession` on the UTC day of `first_seen_at`, zero-filled. This is
the only backend change; business logic was otherwise untouched.

## Intentionally unchanged
- No backend business-logic rewrite, no route/feature deletion.
- No fabricated dashboard numbers — every metric is a real API, best-effort,
  independently guarded.
- Offline-first, local PostgreSQL authoritative, no cloud, no face
  recognition, frontend remains presentation-only (no inference).
- Demo mode stays deterministic and clearly separated (Demo nav entry is
  isDemo-only; badge/banner labels demo vs real data).

## Verification
- `TEST_DATABASE_URL=… .venv/bin/pytest -q` → **487 passed**.
- `npx vitest run` → **153 passed** (incl. new `AppShell.test.tsx` ×4 and the
  rewritten `Dashboard.test.tsx`; `DemoPresentation.test.tsx` is a pre-existing
  flake that passes on re-run).
- `npx tsc -b` clean; `npm run build` green.
- `DATABASE_URL=… .venv/bin/alembic check` → clean (no schema change).

## Limitations
- Stock page "Expiring soon" window and per-product statuses rely on
  reorder-level + batch expiry data; cameras/shelves sections show own empty
  states until the edge runtime records activity.
- Physical/picture verification of the redesigned flow (Phase 32 hardware) still
  needs a human with cameras.
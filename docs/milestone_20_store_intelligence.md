# Milestone 20 — Store Intelligence

**Date:** 2026-09-17
**Status:** ✅ Implemented and verified

---

## Summary

M15–M19 gave Storeye a growing pile of **already-persisted** intelligence: POS
truth (inventory, batches, sales, bills), AI-era evidence (shelf/product/
misplacement observations), anonymous journeys (zones, dwell, transitions) and
alerts. M20 turns that data into **operational insights**: a finding, the
"why" (persisted, auditable evidence), a recommended action, a lifecycle
state, and — for high-impact findings — a synced M16 alert.

```
  INVENTORY/REORDER LEVELS  ──►  LOW_STOCK / OUT_OF_STOCK / HIGH_SELLING_LOW_STOCK
  BATCHES + EXPIRY          ──►  EXPIRY_RISK / EXPIRED_BATCH / STOCK_ROTATION
  SHELF/PRODUCT INTELLIGENCE──►  LOW_SHELF_AVAILABILITY / MISPLACEMENT
  JOURNEY ZONE ANALYTICS    ──►  HIGH_TRAFFIC_ZONE / HIGH_DWELL_ZONE /
  (aggregate, M19)                HIGH_TRAFFIC_LOW_SHELF
  SALES WINDOW              ──►  HIGH_SELLING_LOW_STOCK
  CAMERA STALENESS          ──►  CAMERA_HEALTH (simulated proxy)

        ▼  InsightEngine.evaluate(store_id)
        ▼  (read-only rules → candidates)
        ▼  reconcile: dedup + lifecycle (persisted `insights`) + alert sync
        ▼
  GET /api/insights · summary · store-health · inventory · expiry ·
  customer-flow · {id} · evaluate · acknowledge/resolve/expire
        ▼
  React Insights page + Dashboard "Store Intelligence" card
```

The single most important guarantee: **everything an insight says already
exists elsewhere in the store's own data.** The engine never pokes a camera
API, never talks to a cloud service, never runs an LLM, and never mutates
inventory/batches/sales/bills.

## Hard constraints (encoded, tested)

| Constraint | How it is enforced/tested |
|---|---|
| No new CV pipeline | Rules only read persisted tables; no inference calls |
| No LLM / generative AI | No such service exists in the codebase |
| No cloud / Supabase | Same edge-first, offline-first architecture as M15–M19 |
| No purchase-order execution | No PO model; "recommended action" is human text |
| No mutation of inventory/batches/sales/bills | No-mutation proof tests snapshot rows before/after `evaluate()` |
| No customer-intent claims | "High selling" couples sales to stock level, never to observed people |
| Why is never hidden | Every insight stores `evidence` + `recommended_action`; UI "why" drawer |
| UNKNOWN data is never guessed | Unmapped shelves/products simply produce no insight |
| Privacy | Opaque ids only; flow uses aggregated zone analytics, never identities |

## Rules (deterministic, read-only)

Each rule returns `RuleCandidate`s. `certainty` is **evidence strength**, not
probability of truth; it is never a "confidence score" and never derives
business severity.

| Catalog entry | dtype | Trigger | Severity | Certainty | Alert (≥ `INSIGHT_TO_ALERT_SEVERITY`) |
|---|---|---|---|---|---|
| `inventory.out_of_stock` | `OUT_OF_STOCK` | `quantity == 0` | HIGH | HIGH | SHORTAGE |
| `inventory.low_stock` | `LOW_STOCK` | `0 < qty <= reorder_level` | MEDIUM | HIGH | — |
| `sales.high_selling_low_stock` | `HIGH_SELLING_LOW_STOCK` | qty ≤ reorder AND ≥ `HIGH_SELLING_MIN_UNITS` sold in `HIGH_SELLING_SALES_WINDOW_HOURS` | MEDIUM | HIGH | — |
| `expiry.expired` | `EXPIRED_BATCH` | batch past expiry | HIGH | HIGH | EXPIRY |
| `expiry.expiring_soon` | `EXPIRY_RISK` | expiry within `EXPIRING_SOON_DAYS` (day-precise HIGH, month-precise MEDIUM certainty) | MEDIUM | HIGH/MEDIUM | — |
| `expiry.stock_rotation` | `STOCK_ROTATION_RECOMMENDATION` | ≥ 2 live batches of a product | LOW | MEDIUM | — |
| `shelf_low.low_or_empty` | `LOW_SHELF_AVAILABILITY` | AI shelf state LOW (MEDIUM) or EMPTY (HIGH) | MEDIUM/HIGH | MEDIUM | LOW_SHELF_OCCUPANCY (EMPTY only) |
| `shelf_low.misplacement` | `MISPLACEMENT` | AI product on a shelf whose planogram differs (only when product mapped) | LOW | MEDIUM | — |
| `customer_flow.high_traffic` | `HIGH_TRAFFIC_ZONE` | zone visits ≥ `HIGH_TRAFFIC_MIN_VISITS`, or > `HIGH_TRAFFIC_VISITS_FACTOR`× store avg AND ≥ floor | INFO | HIGH | — |
| `customer_flow.high_dwell` | `HIGH_DWELL_ZONE` | avg dwell ≥ `HIGH_DWELL_MIN_SECONDS` over ≥ `HIGH_DWELL_MIN_VISITS` closed visits | INFO | HIGH | — |
| `customer_flow.high_traffic_low_shelf` | `HIGH_TRAFFIC_LOW_SHELF_AVAILABILITY` | high-traffic zone **and** low/empty shelf there **and** store still has inventory | MEDIUM | MEDIUM | — |
| `camera_health.stale` | `CAMERA_HEALTH` | active camera, no observation in `INSIGHT_CAMERA_STALE_MINUTES` (documented simulated proxy) | HIGH | HIGH | CAMERA_OFFLINE |
| `inventory.low_stock_with_low_shelf` | `LOW_STOCK_WITH_LOW_SHELF_AVAILABILITY` | product low-stock (POS) **and** a low/empty shelf actually shows that product | MEDIUM | MEDIUM | — |

`INVENTORY_RISK` is reserved for future work — nothing in the rule set emits
it; the API/type definitions document it as aggregate-only.

Thresholds live in `backend/app/core/config.py` (`EXPIRING_SOON_DAYS=30`,
`HIGH_TRAFFIC_MIN_VISITS=50`, `HIGH_TRAFFIC_VISITS_FACTOR=1.5`,
`HIGH_DWELL_MIN_SECONDS=180`, `HIGH_DWELL_MIN_VISITS=5`,
`HIGH_SELLING_MIN_UNITS=20`, `HIGH_SELLING_SALES_WINDOW_HOURS=168`,
`INSIGHT_CAMERA_STALE_MINUTES=60`, `INSIGHT_TRAFFIC_WINDOW_HOURS=24`,
`INSIGHT_DWELL_WINDOW_HOURS=24`, `INSIGHT_REFRESH_INTERVAL_SECONDS=300`,
`INSIGHT_EXPIRY_TTL_HOURS=48`, `INSIGHT_TO_ALERT_SEVERITY=HIGH`) and can be
tuned per deployment via env without code changes.

## Evidence format

Every insight ships a persisted `evidence` dict:

```json
{
  "rule": "inventory.low_stock",
  "summary": ["Milk (A-1): current stock 3 units (reorder level: 5)."],
  "sources": [{"source": "inventory", "entity_type": "product", "entity_name": null}],
  "metrics": {"current_stock": 3, "reorder_level": 5, "reorder_quantity": 20},
  "product": {"id": "...", "sku": "AMUL-1L", "name": "Amul Milk 1L"}
}
```

Rule-specific keys exist per domain (batch number in expiry, shelf code in
shelf evidence, `inventory_available` in traffic×shelf, zone id/counts in
customer-flow, `last_observed_at`/`stale_minutes` in camera health). Store
health puts its categorical state inside `summary` with `basis` as human
readable lines. The UI renders evidence as "why" and never hides it.

## Lifecycle & dedup

- Dedup is **application-layer** (mirrors M16): one active (OPEN or
  ACKNOWLEDGED) insight per `(store_id, insight_type, dedupe_key)` where
  `dedupe_key = "{entity_type}:{entity_id}"`. The DB carries a
  **non-unique** index `ix_insights_store_type_key`; correctness is enforced by
  `InsightEngine._load_active` + reconcile.
- Transitions: `OPEN → ACKNOWLEDGED | RESOLVED | EXPIRED`,
  `ACKNOWLEDGED → RESOLVED | EXPIRED`; RESOLVED/EXPIRED are terminal
  (recurrence creates a new row). Invalid transitions → 422.
- Renewed matches update the active row (`refreshed`); a condition that no
  longer holds sets **RESOLVED**; findings with a deadline
  (`expires_at = batch expiry + 1d`) that pass it become **EXPIRED**.
  EXPIRE is also used by `InsightEngine` promotion of stale findings after
  `INSIGHT_EXPIRY_TTL_HOURS`.
- `evaluate()` commits once, rolls back on any error, and returns
  `{created, refreshed, resolved, expired, alerts_created, alerts_updated}`.
- The evaluator is deterministic: callers may pass `reference_date` + `now`
  (used by tests and the demo seeder).

## Store health (categorical, cached, no opaque score)

`StoreHealthService.compute()` derives a single cached `STORE_HEALTH` insight
from current active signal rules using an explicit formula:

```
CRITICAL   if any HIGH/CRITICAL active signal (inventory, camera)
ATTENTION  else if any MEDIUM active signal (inventory, shelf)
HEALTHY    otherwise
```

Prerequisites are enforced before reporting *up*: a camera that is
AI-stale means the rest of the store cannot be confidently assessed, and
shelves with UNKNOWN AI status are excluded from visibility maths. The
response carries `state`, a `basis` list of human-readable reasons, and the
per-domain KPI dicts → the "why" is always shown with the word.

## M16 alert integration

At/above `INSIGHT_TO_ALERT_SEVERITY` (default HIGH, floor MEDIUM), candidates
with a mapped alert type are upserted through `AlertService._upsert_alert`
with `source_type="insights"`, `source_id=dedupe_key`, and the insight
evidence attached to `details`. M16 dedup by `(store, type, product, shelf,
camera)` applies — including absorbing a pre-existing demo alert in the same
context (verified in the demo seeder). Insights explain *why*; alerts demand
*attention*; neither mutates stock.

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /api/insights` | paged + filterable (`category`, `type`, `severity`, `status`, `product_id`, `zone_id`, `camera_id`) |
| `GET /api/insights/summary` | aggregate counts by category/status/severity |
| `GET /api/insights/store-health` | categorical store health + evidence |
| `GET /api/insights/inventory|expiry|customer-flow` | domain-scoped paged lists |
| `POST /api/insights/evaluate` | run rules over existing data (on-demand) |
| `GET /api/insights/{id}` | one insight with full evidence |
| `POST /api/insights/{id}/acknowledge\|resolve\|expire` | lifecycle (validated transitions) |

## Frontend

- **Insights page** (`/app/insights`, primary nav): store-wide KPIs,
  categorical Store Health banner with reason list, category/status filters,
  insight table (severity/status/certainty badges), and a "why" detail modal
  rendering evidence summary, key metrics, context and recommended action.
  "Evaluate now" re-runs the rules and refreshes. Buttons are guard-gated by
  lifecycle (Resolve only on OPEN/ACKNOWLEDGED, etc.).
- **Dashboard**: new "Store Intelligence" card (health state, open insights,
  best categories, high-priority note) that degrades to an empty state when
  the backend is unreachable.
- New `insightApi` module + typed mirror of the backend schemas
  (`src/lib/api/insights.ts`, types in `src/lib/api/types.ts`), new
  `IconLightbulb` nav icon.
- Privacy language is committed to the UI: "Insights never change stock —
  restocking stays an explicit, human-reviewed step."

## Demo data

`backend/scripts/seed_demo.py` now closes with an `InsightEngine.evaluate`
pass over the freshly seeded store (22 insights, 5 insight→alert syncs in the
canonical seed; the count includes the cached `STORE_HEALTH` summary — see the
M21 correction in `milestone_21_demo_scenarios.md`). Seeding stays idempotent; `reset_demo_store` clears `insights`
before reseeding. The inventory is intentionally arranged so the demo shows
the whole rule surface: expired Amul batch, Aashirvaad near-expiry, low/out of
stock staples, low/empty shelves, high-traffic + dwell zones, roof camera
offline, and a high-selling low-stock product.

## Verification

- **Backend (PostgreSQL)**: 298 passed (`test_insights.py` 37 service/rule
  tests including no-mutation proofs, `test_insights_api.py` 12,
  `test_migrations.py` head `3459a7512c9d`), `alembic check` clean.
- **Frontend**: `npx tsc -b` clean, `npx vitest run` 106 passed (10 new for
  M20), `npm run build` green.
- Full green board: 249 (M19) + 49 new = 298 backend tests.

## Privacy recap

Customer-flow insights use only **aggregate** M19 zone analytics (visit counts
and dwell by zone). No journey row, no track id, no embedding, no crop and no
face is read, stored or exposed by any rule. Flow is translated into dwell and
traffic only — never into "this customer wants X".
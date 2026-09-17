# Milestone 22 — Full Integration Audit

**Scope:** M0–M21. This document records how the modules actually integrate, the
gaps found during the M22 audit, and what was changed (or deliberately left
alone). M22 is a hardening/integration milestone — no new product features.

Method: read-only inspection of the backend module graph, the UI route graph,
the configuration surface, the startup path, and the database schema; plus a
full regression run (backend 358 tests, frontend 119 tests, `alembic check`
clean) and real-AI smoke tests.

---

## 1. Module integration map

```
seed / scenario engine
        │  (writes business rows through services)
        ▼
PostgreSQL  ────────────── authoritative business data
   ▲    ▲    ▲    ▲
   │    │    │    └── M20 InsightEngine ──▶ M16 AlertService (dedup)  [insights + alerts]
   │    │    └─────── M19 Journeys (anonymous sessions/zone visits)   [journeys]
   │    └──────────── M15 Product/Shelf Intelligence                  [intelligence]
   └───────────────── M13/M14/M17 AI observations (YOLO/OCR)          [observations]

FastAPI + routers ──▶ service layer ──▶ SQLAlchemy models ──▶ PostgreSQL
                              ▲
        EdgeRuntime (cameras, tracker, Re-ID, annotator) ── observations only
```

The invariant held across every module: **AI/observation layers never mutate
business truth.** Inventory/batches/sales change only through explicit domain
services (`InventoryService`, `BatchService`, billing, Smart Receiving). M20
insights are derived, read-only, and their only side effect is M16 alert
create/refresh through the single alert service.

## 2. Integration gaps found and resolved

| # | Gap | Risk | Resolution |
|---|-----|------|-----------|
| 1 | Configuration was unvalidated: a `sqlite://` `DATABASE_URL`, an out-of-range Re-ID threshold, or an unknown provider would start silently. | Ambiguous/unsafe runtime. | `Settings` field/model validators (`backend/app/core/config.py`). Invalid values now fail fast; SQLite is rejected for the business DB. Covered by `tests/test_config_validation.py` (16 tests). |
| 2 | Startup did no readiness checks; `/api/health` / `/api/ready` reflect only the legacy SQLite diagnostics stack, not PostgreSQL/migrations. | A node could serve traffic with a missing/behind PostgreSQL. | New `app/core/startup.py` (`assess_runtime` / `run_startup_checks`) probes config → PostgreSQL → Alembic head. New `GET /api/system/status` reports the authoritative view. Covered by `tests/test_startup_and_system.py` (5 tests). |
| 3 | Startup/shutdown used deprecated `@app.on_event`. | Deprecation churn; ordering ambiguity. | `create_app()` now uses a single `lifespan` context manager (startup checks → legacy diagnostics DB → serve → edge shutdown → close). Behavior preserved; smoke-tested by the full suite. |
| 4 | No systematic way to assert the persisted DB is internally consistent. | Silent corruption (negative stock, orphans, duplicate inventory, expiry-before-manufacture). | `app/services/integrity_check_service.py` + `python -m scripts.integrity_check [--json]`. Read-only. Covered by `tests/test_integrity_check.py` (8 tests). |
| 5 | A render error in any page blanked the entire React app. | Shopkeeper sees a white screen; looks like data loss. | `frontend/src/components/ErrorBoundary.tsx`, wrapped around the route tree and inside `AppShell` so a page crash keeps navigation. Covered by `ErrorBoundary.test.tsx` (5 tests). |
| 6 | `DEMO_RESET_KEY` existed only as a router constant / raw env read. | Demo guard not part of validated configuration. | Promoted to `Settings.DEMO_RESET_KEY`; the router still falls back to env/constant so behavior is unchanged. |
| 7 | README/AGENTS status drifted (claiming 221/78 tests). | Misleading project state. | Updated during M22. |

## 3. Cross-module checks performed

- **Inventory ↔ reconciliation ↔ observations:** observations never auto-adjust
  inventory; reconciliation results remain advisory; verified by existing
  `test_reconciliation.py` / `test_observations.py`.
- **Shelf/Product intelligence ↔ alerts:** alerts are produced only through the
  M16 `AlertService` dedup path; verified by `test_alerts.py`,
  `test_intelligence.py`.
- **Journeys ↔ privacy:** `global_person_sessions` etc. carry opaque ids only;
  the M22 integrity check asserts no image/embedding/face columns exist.
- **Demo ↔ business truth:** demo state is a single row per demo store in
  `demo_scenario_state`; scenario data lives in normal tables; the service layer
  refuses non-`is_demo` stores (`DemoStoreNotFound`/`NotADemoStore`).
- **AI runtime ↔ API:** `EdgeRuntime` initializes models defensively; missing
  weights degrade to a disabled subsystem rather than crashing the API.

## 4. Deliberately unchanged

- Legacy SQLite/SQLModel diagnostics stack remains (health/ready/metrics). It is
  now explicitly documented as diagnostics-only and is never a business
  fallback.
- `InsightEngine.evaluate_store_health()` (the separate destructive sibling
  resolver) remains for backward compatibility; the demo engine and the main
  evaluate path no longer call it. No new callers were added in M22.
- Public API contracts were extended (new `/api/system/status`), never broken.

## 5. Residual limitations (honest)

- **No authentication/authorization** exists. Demo mutating endpoints rely on
  `X-Demo-Reset-Key`; all other endpoints are unauthenticated. Acceptable for a
  single-tenant, local edge deployment; documented in `docs/privacy_architecture.md`.
- **Camera video sources are metadata** (`camera_type` usb/file/rtsp); no live
  streaming is served by the API.
- The integrity CLI checks structure/invariants, not semantic correctness of
  business decisions (that is out of scope).

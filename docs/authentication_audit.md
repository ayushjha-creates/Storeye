# Storeye Authentication Audit

Status: pre-implementation audit for the Production Authentication Replacement
milestone. This document is the Phase 0 deliverable; it records exactly what the
authentication stub looks like today, what will change, and what must stay
untouched.

---

## 1. Current auth architecture

There is **no server-side authentication** today.

- The FastAPI backend exposes every business router without any auth dependency.
- `backend/app/api/deps.py` provides a single dependency, `get_db()`, which merely
  yields a SQLAlchemy session scoped to one request.
- The frontend has a **UI-level foundation only** (`frontend/src/auth/AuthContext.tsx`):
  - `login()` makes `GET /api/health`, and if the Edge Hub is reachable it records a
    client-side session in `localStorage`.
  - It checks the demo credentials *in the browser* against constants in
    `frontend/src/config/demo.ts` (`demo@storeye.local` / `StoreyeDemo@123`).
  - `ProtectedRoute` redirects unauthenticated visitors to `/login?from=...`.
  - The login page itself displays a disclaimer that authentication is deliberately
    not wired into the backend yet.
- No JWT library, no session table, no password hashing, no cookie handling, no CSRF
  protection. The `Authorization: Bearer` plumbing in `client.ts` exists but is never
  exercised (token is always null).

## 2. Existing models

PostgreSQL business layer (`app/models/`):

- **`User`** (`app/models/user.py`, table `users`):
  `id UUID PK`, `store_id FK -> stores`, `name`, `mobile`, `role` (default
  `"ASSOCIATE"`), `created_at`, `updated_at`. There is **no email, password_hash,
  is_active or last_login_at column**.
- **`Store`** (`app/models/store.py`): name, address, city, phone, timezone, `is_demo`
  (added M21).
- Legacy SQLite/SQLModel diagnostics stack (`app/core/database.py`) also defines a
  `User` (id, store_id, name, role, sync_status) — **diagnostics-only, never a
  business source of truth, must not be changed for the business layer.**

There is no Session/AuthSession table, no role/permission table.

## 3. Existing endpoints

- `app/api/routers/users.py` — unauthenticated CRUD on `/api/users` (list, create,
  get, patch, delete). Creation takes `store_id`, `name`, optional `mobile`, `role`.
- ~19 other business routers (`stores`, `cameras`, `zones`, `shelves`, `products`,
  `inventory`, `customers`, `sales`, `bills`, `notifications`, `observations`,
  `reconciliation`, `intelligence`, `alerts`, `batch_intake`, `demo`, `journeys`,
  `insights`, `mobile_intake`) plus `app/api/edge_api.py` (`/api/edge/*`) — all
  unauthenticated, mostly store-scoped by an explicit `store_id` parameter that any
  caller may supply.
- Open monitoring endpoints that MUST remain unauthenticated: `/api/health`,
  `/api/ready`, `/api/metrics`, `/api/readyz`/`/api/system/status`.
- Demo endpoints: read endpoints (`/api/demo/scenarios`, `/api/demo/status`) are open
  in demo mode; mutating endpoints (`/api/demo/{...}/activate`, `/api/demo/reset`)
  are guarded by the `X-Demo-Reset-Key` header, not by user auth.

## 4. Existing frontend flow

1. `LoginPage` collects name + PIN, calls `login()`.
2. `login()` pings `/api/health`; on success stores `{userName, role, loginAt, demo}`
   in `localStorage` under `storeye.auth.session`.
3. `AuthProvider` (in-memory) exposes `session`, `isAuthenticated`, `isDemo`,
   `login`, `logout`, `apiToken`.
4. `ProtectedRoute`/`PublicOnlyRoute` gate routes based on that in-memory flag.
5. Refresh = reload of the localStorage session (no server confirm).

## 5. Existing weaknesses

- No authentication at all server-side; any local client can read/write every store.
- Demo credentials verified client-side (a fake auth path).
- Auth session persisted in `localStorage`; no HttpOnly cookie.
- No password handling anywhere; users have no credentials.
- `role` exists on `User` but is never enforced.
- `store_id` is fully client-controlled; cross-store access is trivial.
- No session lifecycle, no logout semantics at the server, no password change.
- No CSRF protection, no login throttling, no rate limiting.

## 6. Migration impact

- `users` table gains `email`, `password_hash`, `is_active`, `last_login_at`.
- New `sessions` table (`AuthSession`) storing only a hash of the session secret.
- Existing rows are untouched except additive nullable columns (email backfilled as
  NULL; NULL-email users cannot authenticate until provisioned with credentials).
- Legacy SQLite stack and AI/CV/Re-ID/M25 code are not touched.

## 7. Files that will be modified

Backend:
- `app/models/user.py`, `app/models/__init__.py` (new `AuthSession`)
- new `app/models/auth_session.py`
- new `app/core/auth.py` (argon2 hashing + role constants)
- `app/core/config.py` (session/cookie/password settings)
- `app/schemas/user.py`, new `app/schemas/auth.py`, `app/schemas/__init__.py`
- `app/api/deps.py` (auth dependencies), new `app/api/authz.py` (RBAC + store scope)
- new `app/api/routers/auth.py`
- new `app/services/auth_service.py` (or equivalent)
- `app/main.py` (register auth router)
- all business routers listed in §3 (add auth + store-scope enforcement)
- `scripts/seed_demo.py` (demo user becomes a real credential), possibly `seed.py`
- `backend/alembic/versions/` (new migration)
- `requirements.txt` (+ `argon2-cffi`)

Frontend:
- `src/lib/api/client.ts` (credentials + CSRF header, drop token plumbing)
- new `src/lib/api/auth.ts`
- `src/auth/AuthContext.tsx`, `src/pages/Login.tsx`, `src/pages/Settings.tsx` note
- `src/config/demo.ts` (stop hardcoding the demo password)
- tests: `src/auth/AuthContext.test.tsx`, `src/pages/Login.test.tsx`

Tests:
- HTTP test modules get an authenticated identity override
  (`test_api`, `test_alerts`, `test_batch_intake`, `test_edge_api`,
  `test_insights_api`, `test_journeys_api`).
- new `test_authentication.py` (+ role/isolation regression coverage)

Docs/config:
- `docs/authentication.md` (new), `README.md`, `AGENTS.md`, `.env.example`,
  `frontend/.env.example`.

## 8. Files that must remain untouched

- `app/core/database.py` (legacy SQLite diagnostics stack)
- `app/cv/*`, `app/services/vision/*`, `app/services/ocr.py`, `app/services/tracker.py`,
  `app/services/shelf_detector.py`, `app/services/person_detector.py`
- M19 Re-ID (`app/edge`, reid provider code) — only HTTP-layer deps are added, the
  runtime architecture is unchanged
- M17 Smart Receiving OCR/expiry pipeline
- M25 USB intake watcher/manager internals (`app/services/mobile_intake/manager.py`,
  domain scanner) — the intake architecture is unchanged; only the HTTP router gains
  an auth dependency
- M18/M21 demo *engine* (`app/services/demo/`, `scripts/seed_demo.py` dataset logic
  except the user credential)
- `docker/`, `models/`, `data/`, `runs/`
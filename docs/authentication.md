# Authentication & Authorization

Storeye authenticates staff against its **local PostgreSQL** database. There is
no cloud identity provider, no OAuth/social login, and no public registration —
the deployment is a per-store, offline-first edge app.

- Passwords are stored as **Argon2id** hashes (`argon2-cffi`).
- Login issues an opaque **session secret** in an **HttpOnly cookie**; only the
  SHA-256 hash of the secret is persisted (in the `sessions` table).
- Every business endpoint requires an authenticated user and is **scoped to that
  user's store**.
- Roles (`OWNER` / `MANAGER` / `STAFF`) gate write operations.

## Data model

| Object       | Table      | Notes |
|--------------|------------|-------|
| Account      | `users`    | `email` (unique, nullable), `password_hash`, `is_active`, `last_login_at` added on top of the existing M11 `User` row. |
| Session      | `sessions` | `user_id`, `token_hash` (SHA-256), `expires_at`, `revoked_at`, `user_agent`, `ip_address`. The raw secret is never stored. |

Migration: `backend/alembic/versions/f4a9c0a1b2c3_add_authentication_fields_and_sessions_tab.py`
(head `f4a9c0a1b2c3`).

## Roles

Canonical roles and privilege levels:

| Role      | Level | Intended use |
|-----------|-------|--------------|
| `OWNER`   | 3     | Provisions users, manages the store, everything a MANAGER can do. |
| `MANAGER` | 2     | Catalogue, cameras, notifications, inventory adjustments, alerts/insights lifecycle. |
| `STAFF`   | 1     | Day-to-day reads, sales/bills, receiving stock, batch intake. |

Legacy strings are accepted and mapped at authorization time
(`ASSOCIATE`/`associate`/`staff` → `STAFF`; `STORE_MANAGER`/`Store Manager`/
`manager` → `MANAGER`; `REGIONAL_ADMIN`/`owner` → `OWNER`). New writes
canonicalize to the three canonical roles. See `backend/app/core/auth.py`.

Reads require `STAFF`+ everywhere. Representative write gates:

| Resource | Write gate |
|----------|-----------|
| Products, cameras, zones, shelves, notifications | `MANAGER`+ |
| Customers, sales, bills, inventory receive/movements, batch intake | `STAFF`+ |
| Inventory adjust / reorder / batch create+update | `MANAGER`+ |
| Alerts & insights mutations (evaluate/ack/resolve/dismiss/transitions), reconciliation run | `MANAGER`+ |
| Users, store lifecycle | `OWNER` |

## Store isolation

- `require_same_store(user, store_id)` → **403** when a payload/query names a
  store the caller does not own.
- `scoped_get(db, user, Model, id)` → **404** for a row that is missing *or*
  belongs to another store (existence is not leaked).
- `effective_store_id(user, store_id)` defaults an omitted `store_id` to the
  caller's own store. A client-supplied `store_id` is never trusted.

## HTTP API (`/api/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/login` | CSRF header | Verify email+password, set the session cookie. |
| `POST` | `/api/auth/logout` | session + CSRF | Revoke the current session, clear the cookie. |
| `GET`  | `/api/auth/me` | session | Sanitized current user (never `password_hash`). |
| `POST` | `/api/auth/change-password` | session + CSRF | Rotate the password; revoke all **other** sessions. |
| `POST` | `/api/auth/logout-all` | session + CSRF | Revoke every session for the user. |

Login failures always return the same generic `401 Invalid email or password`
(unknown email, wrong password, inactive account). Repeated failures are throttled
per `(email, client)` in memory (`AUTH_LOGIN_MAX_ATTEMPTS`, default 8 within
`AUTH_LOGIN_THROTTLE_SECONDS`, default 900 s) → `429`.

### CSRF

State-changing auth endpoints require the custom header `X-Storeye-CSRF: 1`
(configurable). A cross-site form cannot set custom headers; combined with the
`SameSite=Lax` cookie and the strict local CORS allow-list this is the CSRF
control. The frontend client sends it automatically on non-GET requests.

> **No public registration.** Accounts are created by an owner via
> `POST /api/users` (OWNER-only) or by the seed scripts.

## Configuration

All settings live in `backend/app/core/config.py` and are documented in
`.env.example`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `AUTH_COOKIE_NAME` | `storeye_session` | Session cookie name. |
| `AUTH_COOKIE_SECURE` | `false` | Set `true` behind HTTPS. |
| `AUTH_COOKIE_SAMESITE` | `lax` | `lax`/`strict`/`none`. |
| `AUTH_SESSION_TTL_HOURS` | `12` | Session lifetime. |
| `AUTH_PASSWORD_MIN_LENGTH` | `8` | Minimum password length (>= 8). |
| `AUTH_LOGIN_MAX_ATTEMPTS` | `8` | Failures before throttling. |
| `AUTH_LOGIN_THROTTLE_SECONDS` | `900` | Throttle window. |
| `AUTH_CSRF_HEADER` | `X-Storeye-CSRF` | CSRF header name. |
| `AUTH_CSRF_VALUE` | `1` | CSRF header value. |

## Seeded accounts

| Script | Email | Password | Role |
|--------|-------|----------|------|
| `backend/scripts/seed.py` | `owner@storeye.local` | `StoreyeOwner@123` | `OWNER` |
| `backend/scripts/seed_demo.py` | `demo@storeye.local` | `StoreyeDemo@123` | `OWNER` (demo store) |

Change these before any shared deployment. The frontend does **not** contain the
demo password (only non-secret display hints in `frontend/src/config/demo.ts`).

## Frontend

- `frontend/src/lib/api/client.ts` sends `credentials: 'include'` and the CSRF
  header; there is **no** bearer token and nothing auth-related in
  `localStorage`.
- `frontend/src/lib/api/auth.ts` wraps the five auth endpoints.
- `frontend/src/auth/AuthContext.tsx` restores the session via `GET /api/auth/me`
  on load and exposes `login`, `logout`, `logoutAll`, `changePassword`, plus
  `isLoading` so route guards don't flash before restore completes.
- `frontend/src/pages/Login.tsx` posts real credentials (email + password).
- `frontend/src/pages/Settings.tsx` shows the signed-in identity and offers
  change-password / sign-out-everywhere.

## Tests

- `backend/tests/test_authentication.py` — 24 end-to-end cases (login, generic
  failures, CSRF, `/me`, expiry, revocation, logout, logout-all,
  change-password, throttle, cross-store 403/404, RBAC).
- Domain HTTP tests bind a fake authenticated user via
  `tests/conftest.py:bind_test_user(store_id, role)`; the authorization plumbing
  itself stays live.

## Known limitations

- The login throttle is in-process (single edge node) and resets on restart.
- `AUTH_COOKIE_SECURE` defaults to `false` for local HTTP; enable it for HTTPS.
- Demo mutating endpoints additionally rely on the shared `DEMO_RESET_KEY`; this
  is documented as a limitation in `docs/privacy_architecture.md`.

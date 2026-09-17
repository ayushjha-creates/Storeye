# Storeye — Update & Rollback

Keep Storeye current without breaking the edge node. This document assumes the
deployment is managed by the `scripts/` suite (see `docs/quickstart_edge.md`).

---

## 1. Update workflow (git-based)

```bash
# 0. safety net first (always)
./scripts/storeye backup                       # pg_dump → backups/
git log --oneline -5                          # note the current commit for rollback

# 1. stop the running node
./scripts/storeye stop

# 2. pull the new version
git pull

# 3. verify hashes / build integrity (optional)
git status --short

# 4. re-run the idempotent setup (picks up new Python/JS deps)
./scripts/setup.sh                            # safe to re-run

# 5. apply database migrations (the critical step)
./scripts/storeye migrate                     # alembic upgrade head + check

# 6. doctor + integrity before serving traffic
./scripts/storeye doctor --fast
(cd backend && ./.venv/bin/python -m scripts.integrity_check)

# 7. start and verify
./scripts/storeye start
curl -fsS http://localhost:8000/api/system/status   # status OK, migration_current true
```

Migrations are **one-way** and transactional (Alembic). They never drop data
by themselves; `scripts/migrate.sh` also runs `alembic check` to detect drift.

## 2. Demo data after an update

- `./scripts/storeye seed` is idempotent → safe after an update.
- If a migration changed the demo store, a full rebuild is:
  `./scripts/storeye demo-reset` (destructive to the **demo store only**).

## 3. Rollback plan

There are two independent rollback axes — do not conflate them.

### a) Roll back the application code (no migration involved)

```bash
./scripts/storeye stop
git checkout <previous-commit>
./scripts/setup.sh                       # reinstall deps for that commit
./scripts/storeye start                  # old code against the current schema
```

Only safe when the previous commit did **not** change the schema (no migration
in the rolled-back range). Check: `git diff <prev>..<new> -- backend/alembic`.

### b) Roll back schema + data (migration was applied)

Alembic `downgrade` is available but **not** the default push-button path,
because data written under the newer schema can make a downgrade lossy.

Preferred, deterministic procedure:

1. You backed up immediately before the update (`./scripts/storeye backup`).
2. `./scripts/storeye stop`
3. `./scripts/storeye restore backups/storeye-<pre-update>.dump --yes`
4. `git checkout <previous-commit>`
5. `./scripts/setup.sh && ./scripts/storeye migrate && ./scripts/storeye doctor`
6. `./scripts/storeye start` and verify `/api/system/status`.

If the schema changed and you must stay on the new schema but revert code,
that combination is unsupported — always pair a schema revert with the data
restore above.

## 4. Update risk table

| Change in release | Rollback strategy |
|-------------------|-------------------|
| code-only (no `backend/alembic` diff) | `a)` checkout previous commit + restart |
| added migration (append-only) | `a)` works; `b)` if you must remove the migration |
| destructive/backfilled migration | force `b)` (backup restore) — never a plain downgrade |
| frontend-only | rebuild `npm run build` for the pinned version |
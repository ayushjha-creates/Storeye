# Storeye — Backup & Restore

PostgreSQL (`storeye`) is the source of truth: all business entities (stores,
inventory, batches, alerts, insights, demo state) live there. Back it up
regularly. AI weights and the frontend build are static and can be re-fetched
from the repo — no backup required (see `docs/model_assets.md`).

---

## 1. Automatic helper

```bash
./scripts/storeye backup                  # dumps the business DB → backups/
./scripts/storeye backup --all            # business DB + test DB
./scripts/storeye backup --test-db        # test DB only
./scripts/storeye backup --out /mnt/nas   # custom destination
```

- Format: PostgreSQL **custom** (`pg_dump --format=custom --no-owner --no-privileges`).
- Filename: `backups/<db>-<YYYYmmdd-HHMMSS>.dump`.
- `backups/` is git-ignored; `STOREYE_BACKUP_DIR` overrides the location.

## 2. Scheduling

```bash
# crontab (macOS/Linux) — nightly at 02:00
0 2 * * * cd /path/to/Storeye && ./scripts/storeye backup >> logs/run/backup.log 2>&1
```

Then copy `backups/` off-box (iCloud/NAS/object store). A backup that never
leaves the disk is not a backup.

## 3. Restore

```bash
./scripts/storeye restore backups/storeye-20260917-085140.dump --yes
./scripts/storeye restore backups/storeye_test-20260917-085140.dump --yes --test-db
```

**Destructive**: the target database is dropped and recreated first. `--yes`
is required. `pg_restore` runs with `--no-owner --no-privileges`.

After restoring the business DB, resync Alembic (and the demo store if needed):

```bash
./scripts/storeye migrate             # alembic upgrade head + check
./scripts/storeye doctor              # confirm every check is PASS/acceptable
(cd backend && ./.venv/bin/python -m scripts.integrity_check)  # M22 integrity audit
```

## 4. Manual equivalent (if you operate PostgreSQL yourself)

```bash
export PGPASSWORD=... # or use trust/peer as in the dev cluster
pg_dump  -h localhost -p 5433 -U storeye --format=custom -f storeye.dump storeye
dropdb   -h localhost -p 5433 -U storeye storeye
createdb -h localhost -p 5433 -U storeye storeye
pg_restore -h localhost -p 5433 -U storeye --no-owner --no-privileges -d storeye storeye.dump
```

## 5. Restore checklist

1. `./scripts/storeye stop` (no writers).
2. Restore into a **scratch** DB first and run
   `python -m scripts.integrity_check` against it to confirm health.
3. Restore into `storeye`, run `./scripts/storeye migrate`, then
   `./scripts/storeye doctor --fast`.
4. Start, verify `/api/system/status` → `status OK`, `migration_current true`.

## 6. What NOT to back up

- `models/`, `frontend/dist/`, `node_modules/`, `.venv/`, `logs/` — regenerable.
- Raw video frames — none are ever persisted (privacy principle).
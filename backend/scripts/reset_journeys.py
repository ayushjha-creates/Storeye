"""M27 Phase 6/27 — journey-scoped development reset.

Deletes ONLY anonymous journey data for one store (or all stores):

    global_person_sessions
    person_track_associations
    zone_visits
    person_camera_transitions

It never touches observations, inventory, batches, bills, sales, products,
cameras or users. Meant for cleaning up corrupted test data (e.g. a single
person producing dozens of journeys) during development.

Usage (from `backend/`):

    # Preview what would be deleted (no writes):
    DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye" \
        ./.venv/bin/python -m scripts.reset_journeys --store-id <UUID> --dry-run

    # Actually delete, for a non-demo store (requires --yes):
    ./.venv/bin/python -m scripts.reset_journeys --store-id <UUID> --yes

    # Every store at once (still requires --yes):
    ./.venv/bin/python -m scripts.reset_journeys --all --yes

Safety rules:
  * `--yes` is mandatory for any write; without it the command prints what it
    WOULD do and exits 2.
  * A store flagged `is_demo` is refused unless `--include-demo` is also given,
    so the deterministic demo baseline is never wiped accidentally (use the
    Demo Control Center for that).
"""

from __future__ import annotations

import argparse
import sys
from uuid import UUID

from sqlalchemy import delete, func, select

from app.db.session import dispose_engine, get_session, init_engine
from app.models import (
    GlobalPersonSession,
    PersonCameraTransition,
    PersonTrackAssociation,
    Store,
    ZoneVisit,
)

_TABLES = (
    ("person_track_associations", PersonTrackAssociation),
    ("person_camera_transitions", PersonCameraTransition),
    ("zone_visits", ZoneVisit),
    ("global_person_sessions", GlobalPersonSession),
)


def _counts(session, store_id) -> dict:
    out: dict = {}
    for name, model in _TABLES:
        stmt = select(func.count()).select_from(model)
        if store_id is not None:
            stmt = stmt.where(model.store_id == store_id)
        out[name] = int(session.scalar(stmt) or 0)
    return out


def _delete(session, store_id) -> dict:
    out: dict = {}
    for name, model in _TABLES:
        stmt = delete(model)
        if store_id is not None:
            stmt = stmt.where(model.store_id == store_id)
        out[name] = session.execute(stmt).rowcount or 0
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reset_journeys",
        description="Delete ONLY anonymous journey rows for a store (dev/demo cleanup).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--store-id", help="UUID of the store whose journeys to delete")
    group.add_argument("--all", action="store_true", help="delete journeys for every store")
    parser.add_argument(
        "--include-demo",
        action="store_true",
        help="also allow deleting journeys of a store flagged is_demo",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm the destructive write (without it this is a dry run)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="force a dry run even with --yes"
    )
    args = parser.parse_args(argv)

    store_id = None
    if args.store_id:
        try:
            store_id = UUID(args.store_id)
        except ValueError:
            print(f"error: --store-id is not a valid UUID: {args.store_id}", file=sys.stderr)
            return 2

    init_engine()
    session = get_session()
    try:
        if store_id is not None:
            store = session.get(Store, store_id)
            if store is None:
                print(f"error: no store with id {store_id}", file=sys.stderr)
                return 1
            if store.is_demo and not args.include_demo:
                print(
                    f"refusing: store {store_id} is a DEMO store "
                    f"({store.name!r}). Re-run with --include-demo if that is intended, "
                    "or use the Demo Control Center.",
                    file=sys.stderr,
                )
                return 1
            scope = f"store {store_id} ({store.name!r})"
        else:
            demos = session.scalars(select(Store).where(Store.is_demo.is_(True))).all()
            if demos and not args.include_demo:
                names = ", ".join(f"{s.id} ({s.name!r})" for s in demos)
                print(
                    "refusing: --all would delete DEMO store journeys too "
                    f"({names}). Re-run with --include-demo if that is intended.",
                    file=sys.stderr,
                )
                return 1
            scope = "ALL stores"

        counts = _counts(session, store_id)
        print(f"Storeye journey reset — scope: {scope}")
        for name, n in counts.items():
            print(f"  {name}: {n}")

        if not args.yes or args.dry_run:
            print("DRY RUN — nothing deleted. Re-run with --yes to apply.")
            return 0

        deleted = _delete(session, store_id)
        session.commit()
        print("Deleted:")
        for name, n in deleted.items():
            print(f"  {name}: {n}")
        print("Done. Observations/inventory/batches/bills/sales were NOT touched.")
        return 0
    finally:
        session.close()
        dispose_engine()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

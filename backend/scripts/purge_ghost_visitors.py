"""Clean up one-frame 'ghost visitor' sessions created by detector noise.

The edge pipeline only promotes a local track to a session/journey after
`stable_track_min_frames` consecutive detections. Before that gate was on by
default, single-frame detector blips (motion flicker, low-res cameras, fast
ByteTrack id churn) each minted a fresh ``GlobalPersonSession`` that the
journey dashboards counted as a real visitor with ~0s dwell. Use this script
after upgrading to delete those ghost rows from a store.

Deletes ONLY ghost sessions (duration < ``--min-duration-seconds``) and their
cascade children (track associations / transitions / zone visits). Journey
tables only — products/inventory/batches/bills/sales/observations are never
touched.

Usage (from `backend/`):

    # Preview what would be deleted (no writes):
    ./.venv/bin/python -m scripts.purge_ghost_visitors --store-id <UUID>

    # Actually delete (requires --yes):
    ./.venv/bin/python -m scripts.purge_ghost_visitors --store-id <UUID> --yes

Safety rules:
  * `--yes` is mandatory for any write; without it the command prints what it
    WOULD do and exits 2.
  * A store flagged `is_demo` is refused unless `--include-demo` is also given.
"""

from __future__ import annotations

import argparse
import sys
from uuid import UUID

from sqlalchemy import func, select

from app.db.session import dispose_engine, get_session, init_engine
from app.models import GlobalPersonSession, Store


def _preview(session, store_id: UUID, min_duration_s: float) -> dict:
    ghost = _ghost_sessions_select(session, store_id, min_duration_s).subquery()
    return {"ghost_sessions": int(session.scalar(select(func.count()).select_from(ghost)) or 0)}


def _ghost_sessions_select(session, store_id: UUID, min_duration_s: float):
    duration = func.extract(
        "epoch", GlobalPersonSession.last_seen_at - GlobalPersonSession.first_seen_at
    )
    return select(GlobalPersonSession.id).where(
        GlobalPersonSession.store_id == store_id,
        duration < min_duration_s,
    )


def _delete(session, store_id: UUID, min_duration_s: float = 1.0) -> dict:
    """Delete ghost sessions; children cascade via session_id FKs. Returns counts."""
    ids = session.scalars(_ghost_sessions_select(session, store_id, min_duration_s)).all()
    if not ids:
        return {"ghost_sessions": 0, "cascade_children": 0}

    from app.models import PersonCameraTransition, PersonTrackAssociation, ZoneVisit

    safe = [str(i) for i in ids]
    children = 0
    for model in (PersonTrackAssociation, PersonCameraTransition, ZoneVisit):
        children += int(
            session.scalar(
                select(func.count()).select_from(model).where(
                    model.session_id.in_(safe)
                )
            )
            or 0
        )
    session.execute(
        GlobalPersonSession.__table__.delete().where(
            GlobalPersonSession.id.in_(ids)
        )
    )
    return {"ghost_sessions": len(ids), "cascade_children": children}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="purge_ghost_visitors",
        description="Delete single-frame 'ghost visitor' sessions for a store.",
    )
    parser.add_argument("--store-id", required=True, help="UUID of the store to clean")
    parser.add_argument(
        "--min-duration-seconds",
        type=float,
        default=1.0,
        help="sessions shorter than this are ghosts (default: 1.0)",
    )
    parser.add_argument(
        "--include-demo",
        action="store_true",
        help="also allow purging a store flagged is_demo",
    )
    parser.add_argument(
        "--yes", action="store_true", help="confirm the destructive write"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="force a dry run even with --yes"
    )
    args = parser.parse_args(argv)

    try:
        store_id = UUID(args.store_id)
    except ValueError:
        print(f"error: --store-id is not a valid UUID: {args.store_id}", file=sys.stderr)
        return 2

    if args.min_duration_seconds <= 0:
        print("error: --min-duration-seconds must be > 0", file=sys.stderr)
        return 2

    init_engine()
    session = get_session()
    try:
        store = session.get(Store, store_id)
        if store is None:
            print(f"error: no store with id {store_id}", file=sys.stderr)
            return 1
        if store.is_demo and not args.include_demo:
            print(
                f"refusing: store {store_id} is a DEMO store ({store.name!r}). "
                "Re-run with --include-demo if that is intended.",
                file=sys.stderr,
            )
            return 1

        preview = _preview(session, store_id, args.min_duration_seconds)
        print(
            f"Storeye ghost-visitor purge — store {store_id} ({store.name!r}), "
            f"duration < {args.min_duration_seconds}s"
        )
        for name, n in preview.items():
            print(f"  {name}: {n}")

        if not args.yes or args.dry_run:
            print("DRY RUN — nothing deleted. Re-run with --yes to apply.")
            return 0

        deleted = _delete(session, store_id, args.min_duration_seconds)
        session.commit()
        print("Deleted:")
        for name, n in deleted.items():
            print(f"  {name}: {n}")
        print(
            "Done. Track associations / transitions / zone visits cascade-deleted. "
            "Observations/inventory/batches/bills/sales were NOT touched.\n"
            "Tip: keep PERSON_STABLE_TRACK_MIN_FRAMES default (5) so future "
            "single-frame blips stay candidates and never become sessions."
        )
        return 0
    finally:
        session.close()
        dispose_engine()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
"""M29 — Retention purge for minimal person analytics (journey tables) + observations.

Deletes ONLY the oldest rows from these tables (never products/inventory/batches/bills/sales):

    * PersonTrackAssociation  (last_seen_at < cutoff)
    * PersonCameraTransition  (transitioned_at < cutoff)
    * ZoneVisit               (entered_at < cutoff)
    * GlobalPersonSession     (last_seen_at < cutoff)
    * Observation             (observed_at < cutoff, PERSON only)

Usage (from `backend/`):

    # Preview what would be deleted (no writes):
    DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye" \
        ./.venv/bin/python -m scripts.purge_analytics --store-id <UUID> --dry-run

    # Actually delete, for a non-demo store (requires --yes):
    ./.venv/bin/python -m scripts.purge_analytics --store-id <UUID> --yes

    # Every store at once (still requires --yes):
    ./.venv/bin/python -m scripts.purge_analytics --all --yes

Safety rules:
  * `--yes` is mandatory for any write; without it the command prints what it
    WOULD do and exits 2.
  * A store flagged `is_demo` is refused unless `--include-demo` is also given,
    so the deterministic demo baseline is never wiped accidentally.
"""

from __future__ import annotations

import argparse
import sys
from uuid import UUID

from sqlalchemy import func, select

from app.db.session import dispose_engine, get_session, init_engine
from app.models import (
    GlobalPersonSession,
    Observation,
    OBS_PERSON,
    PersonCameraTransition,
    PersonTrackAssociation,
    Store,
    ZoneVisit,
)


def _preview_counts(session, store_id: UUID, journey_days: int, obs_hours: int) -> dict:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    j_cutoff = now - timedelta(days=journey_days)
    o_cutoff = now - timedelta(hours=obs_hours)

    out: dict = {}
    # Journey tables keyed by last_seen_at/transitioned_at/entered_at.
    for name, model, col in (
        ("person_track_associations", PersonTrackAssociation, PersonTrackAssociation.last_seen_at),
        ("person_camera_transitions", PersonCameraTransition, PersonCameraTransition.transitioned_at),
        ("zone_visits", ZoneVisit, ZoneVisit.entered_at),
        ("global_person_sessions", GlobalPersonSession, GlobalPersonSession.last_seen_at),
    ):
        stmt = select(func.count()).select_from(model).where(
            model.store_id == store_id, col < j_cutoff
        )
        out[name] = int(session.scalar(stmt) or 0)

    out["person_observations"] = int(
        session.scalar(
            select(func.count()).select_from(Observation).where(
                Observation.store_id == store_id,
                Observation.observation_type == OBS_PERSON,
                Observation.observed_at < o_cutoff,
            )
        )
        or 0
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="purge_analytics",
        description="M29 retention purge: old person journey analytics + PERSON observations.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--store-id", help="UUID of the store whose analytics to purge")
    group.add_argument("--all", action="store_true", help="purge analytics for every store")
    parser.add_argument(
        "--include-demo",
        action="store_true",
        help="also allow purging a store flagged is_demo",
    )
    parser.add_argument(
        "--journey-retention-days",
        type=int,
        default=30,
        help="delete journey rows older than this (default: 30)",
    )
    parser.add_argument(
        "--observation-retention-hours",
        type=int,
        default=24,
        help="delete PERSON observations older than this (default: 24)",
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
                    f"({store.name!r}). Re-run with --include-demo if that is intended.",
                    file=sys.stderr,
                )
                return 1
            scope = f"store {store_id} ({store.name!r})"
        else:
            demos = session.scalars(select(Store).where(Store.is_demo.is_(True))).all()
            if demos and not args.include_demo:
                names = ", ".join(f"{s.id} ({s.name!r})" for s in demos)
                print(
                    "refusing: --all would delete DEMO store analytics too "
                    f"({names}). Re-run with --include-demo if that is intended.",
                    file=sys.stderr,
                )
                return 1
            scope = "ALL stores"

        preview = _preview_counts(
            session,
            store_id,  # type: ignore[arg-type]
            args.journey_retention_days,
            args.observation_retention_hours,
        )
        print(f"Storeye M29 analytics purge — scope: {scope}")
        for name, n in preview.items():
            print(f"  {name}: {n}")

        if not args.yes or args.dry_run:
            print("DRY RUN — nothing deleted. Re-run with --yes to apply.")
            return 0

        from app.services.journeys import JourneyService
        from app.services.observations.observation_service import ObservationService

        j = JourneyService(session)
        deleted = j.purge_analytics(
            store_id=store_id,  # type: ignore[arg-type]
            retention_days=args.journey_retention_days,
        )
        o = ObservationService(session)
        deleted["person_observations"] = o.purge_person_observations(
            store_id=store_id,  # type: ignore[arg-type]
            retention_hours=args.observation_retention_hours,
        )
        print("Deleted:")
        for name, n in deleted.items():
            print(f"  {name}: {n}")
        print(
            "Done. Observations/inventory/batches/bills/sales/products/cameras were NOT "
            "touched (except PERSON observations above)."
        )
        return 0
    finally:
        session.close()
        dispose_engine()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

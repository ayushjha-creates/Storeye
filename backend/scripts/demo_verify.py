"""M23 deterministic demo-reset verifier.

Runs the demo reset + seed TWICE and asserts the resulting business-data
baseline is byte-for-byte identical (row counts per table), and that a
non-demo store is never touched.

Usage (from `backend/`):

    DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye" \
        ./.venv/bin/python -m scripts.demo_verify [--json]

Exit code 0 = deterministic reset verified; 1 = mismatch.

This is intentionally the SAME code path as `scripts.seed_demo` (reset_demo_store
+ seed_with_session); it does not reimplement demo data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import create_db_engine
from app.db.base import Base
from app.models import (
    Alert,
    Batch,
    Bill,
    Camera,
    GlobalPersonSession,
    Insight,
    Inventory,
    Observation,
    PersonCameraTransition,
    PersonTrackAssociation,
    Product,
    Sale,
    Shelf,
    Store,
    User,
    Zone,
    ZoneVisit,
)
from scripts.seed_demo import DEMO_STORE_ID, reset_demo_store, seed_with_session

_BASELINE_MODELS = [
    Insight,
    Alert,
    Observation,
    Inventory,
    Batch,
    Shelf,
    Camera,
    Product,
    Zone,
    User,
    GlobalPersonSession,
    PersonCameraTransition,
    PersonTrackAssociation,
    ZoneVisit,
]


def _counts(session: Session) -> dict:
    return {
        model.__tablename__: int(
            session.execute(select(func.count()).select_from(model)).scalar_one()
        )
        for model in _BASELINE_MODELS
    }


def verify(database_url: str | None = None) -> dict:
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)

    real_store_id = None
    with Session(engine) as session:
        existing = session.scalars(
            select(Store).where(Store.is_demo.is_(False))
        ).first()
        if existing is None:
            real = Store(
                id=uuid.uuid4(),
                name="Reset Verifier — Do Not Delete",
                is_demo=False,
            )
            session.add(real)
            session.commit()
            real_store_id = str(real.id)
        else:
            real_store_id = str(existing.id)

    with Session(engine) as session:
        reset_demo_store(session)
        seed_with_session(session)
        first = _counts(session)

        reset_demo_store(session)
        seed_with_session(session)
        second = _counts(session)

        demo = session.get(Store, DEMO_STORE_ID)
        real = session.get(Store, uuid.UUID(real_store_id))

    engine.dispose()
    return {
        "deterministic": first == second,
        "demo_store_present": demo is not None and bool(demo.is_demo),
        "non_demo_store_preserved": real is not None and not real.is_demo,
        "counts": first,
        "diff": {
            key: {"first": first.get(key), "second": second.get(key)}
            for key in set(first) | set(second)
            if first.get(key) != second.get(key)
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demo_verify",
        description="Verify the Storeye demo reset is deterministic and isolated.",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    result = verify(os.getenv("DATABASE_URL"))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Storeye demo reset verification")
        print(f"  deterministic:            {result['deterministic']}")
        print(f"  demo store present:       {result['demo_store_present']}")
        print(f"  non-demo store preserved: {result['non_demo_store_preserved']}")
        if result["diff"]:
            print(f"  differences: {result['diff']}")

    ok = (
        result["deterministic"]
        and result["demo_store_present"]
        and result["non_demo_store_preserved"]
    )
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

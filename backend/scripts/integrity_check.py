"""M22 integrity-check CLI.

Usage (from `backend/`):

    DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye" \
        ./.venv/bin/python -m scripts.integrity_check
    ./.venv/bin/python -m scripts.integrity_check --json

Exit code 0 = no errors; 1 = at least one integrity error.

The spec named this module `backend.services.integrity_check`; this repository
uses the `app.services.*` package layout and `scripts.*` entry points, so the
check *service* lives at `app.services.integrity_check_service` and this thin
CLI wrapper is invoked as `python -m scripts.integrity_check` from `backend/`.

Read-only: this command never mutates business data.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db.session import dispose_engine, get_session, init_engine
from app.services.integrity_check_service import IntegrityCheckService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="integrity_check",
        description="Read-only Storeye business-database integrity check.",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    init_engine()
    session = get_session()
    try:
        report = IntegrityCheckService(session).run()
    finally:
        session.close()
        dispose_engine()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print("Storeye integrity check")
        print(f"  status:   {'OK' if report.ok else 'FAILED'}")
        print(f"  errors:   {len(report.errors)}")
        print(f"  warnings: {len(report.warnings)}")
        print(f"  stats:    {report.stats}")
        for finding in report.findings:
            print(f"  [{finding.severity.upper()}] {finding.check}: {finding.message} ({finding.count})")
        if report.ok and not report.warnings:
            print("  no issues found")

    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

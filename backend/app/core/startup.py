"""M22 startup sequence.

Deterministic, side-effect-free verification order:

    configuration validation
          |
          v
    PostgreSQL connectivity          (skipped when DATABASE_URL is unset)
          |
          v
    Alembic migration readiness
          |
          v
    application initialization       (legacy diagnostics DB + routers)
          |
          v
    optional AI runtime              (lazy; never blocks the business API)

This module never mutates business data. It only *reports*; the caller decides
whether a problem is fatal. In production (or with ``STRICT_STARTUP=true``) a
missing/misconfigured PostgreSQL or a schema behind Alembic head is fatal; in
development and tests it is logged as a clear warning so the API can still boot
for diagnostics.

The PostgreSQL probe is intentionally skipped under pytest so the test suite
never connects to the development/production business database by accident.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import create_engine, text

from .config import get_settings
from .logging import get_logger

logger = get_logger("storeye.startup")


@dataclass
class StartupReport:
    config_ok: bool = True
    database_configured: bool = False
    database_reachable: bool = False
    migration_current: Optional[bool] = None
    migration_head: Optional[str] = None
    migration_db_revision: Optional[str] = None
    reid_enabled: bool = False
    strict: bool = False
    fatal: bool = False
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "config_ok": self.config_ok,
            "database_configured": self.database_configured,
            "database_reachable": self.database_reachable,
            "migration_current": self.migration_current,
            "migration_head": self.migration_head,
            "migration_db_revision": self.migration_db_revision,
            "reid_enabled": self.reid_enabled,
            "strict": self.strict,
            "fatal": self.fatal,
            "messages": list(self.messages),
        }


def expected_alembic_head() -> Optional[str]:
    """Return the head revision from the migration scripts, or None."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        base = get_settings().BASE_DIR
        cfg = Config(str(base / "alembic.ini"))
        cfg.set_main_option("script_location", str(base / "alembic"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not resolve Alembic head: %s", exc)
        return None


def _probe_postgres(url: str) -> tuple[bool, Optional[str], Optional[str], list[str]]:
    """Connect once and read the current Alembic revision.

    Returns (reachable, db_revision, head, messages).
    """
    messages: list[str] = []
    engine = create_engine(url, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_rev: Optional[str] = None
            try:
                db_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except Exception:
                messages.append("alembic_version table not found (schema not migrated?)")
            return True, db_rev, expected_alembic_head(), messages
    except Exception as exc:
        messages.append(f"PostgreSQL unreachable: {exc.__class__.__name__}: {exc}")
        return False, None, expected_alembic_head(), messages
    finally:
        engine.dispose()


def assess_runtime(*, probe_database: bool = True, skip_in_tests: bool = True) -> StartupReport:
    """Run the startup checks and return a report. Never raises (except config)."""
    report = StartupReport()
    try:
        settings = get_settings()
        report.config_ok = True
    except Exception as exc:
        report.config_ok = False
        report.fatal = True
        report.messages.append(f"Invalid configuration: {exc}")
        return report

    report.strict = settings.is_strict
    report.reid_enabled = bool(settings.REID_ENABLED)
    report.migration_head = expected_alembic_head()

    if not settings.DATABASE_URL:
        report.messages.append(
            "DATABASE_URL is not set; business APIs will fail until it is configured."
        )
        report.fatal = report.strict
        return report

    report.database_configured = True

    if not probe_database or (skip_in_tests and "pytest" in sys.modules):
        report.messages.append("Database probe skipped (test/dev context).")
        return report

    reachable, db_rev, head, msgs = _probe_postgres(settings.DATABASE_URL)
    report.database_reachable = reachable
    report.migration_db_revision = db_rev
    if head:
        report.migration_head = head
    report.messages.extend(msgs)

    if reachable:
        if report.migration_head and db_rev == report.migration_head:
            report.migration_current = True
        else:
            report.migration_current = False
            report.messages.append(
                f"Schema revision {db_rev!r} does not match Alembic head "
                f"{report.migration_head!r}; run `alembic upgrade head`."
            )
    else:
        report.fatal = True

    if report.migration_current is False:
        report.fatal = report.strict

    return report


def run_startup_checks(*, probe_database: bool = True) -> StartupReport:
    """Assess the runtime and raise only when the deployment is strict."""
    report = assess_runtime(probe_database=probe_database)

    logger.info(
        "Startup checks | config_ok=%s db_configured=%s db_reachable=%s "
        "migration_current=%s reid=%s strict=%s",
        report.config_ok,
        report.database_configured,
        report.database_reachable,
        report.migration_current,
        report.reid_enabled,
        report.strict,
    )
    for msg in report.messages:
        logger.warning("Startup notice: %s", msg)

    if report.fatal and report.strict:
        raise RuntimeError(
            "Storeye startup refused: required configuration/database is not ready. "
            + " ".join(report.messages)
        )
    return report

from __future__ import annotations

import os
import re

import pytest

# Force legacy test DB path (legacy SQLite diagnostics only) before any app imports.
os.environ["EDGERETAIL_DATA_DIR"] = "/tmp/edgeretail_test"

# ---------------------------------------------------------------------------
# Test-database safety: business/data tests MUST run against an isolated,
# PostgreSQL-only test database — never the production `storeye` database and
# never a silent SQLite fallback.
#
# TEST_DATABASE_URL is picked up by every PostgreSQL-backed test module
# (test_api, test_database, test_inventory_domain, test_observations,
# test_reconciliation, test_intelligence, test_migrations). This conftest
# guard fails the whole suite loudly if it is missing, non-PostgreSQL, or
# pointed at the production database.
# ---------------------------------------------------------------------------

DEFAULT_TEST_DB_URL = "postgresql+psycopg2://storeye@localhost:5433/storeye_test"
PRODUCTION_DB_NAME = "storeye"


def resolve_test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL is required for Storeye tests and must point at "
            "PostgreSQL. Refusing to fall back to a temporary SQLite database."
        )
    if not re.match(r"^postgresql(?:\+\w+)?://", url):
        raise RuntimeError(
            f"TEST_DATABASE_URL must be a PostgreSQL URL, got: {url!r}. "
            "Business tests must run against PostgreSQL (storeye_test)."
        )
    # Extract the database name (the path component right after the last '/').
    match = re.search(r"/([^/?#]+)$", url.split("?")[0].split("#")[0])
    db_name = match.group(1) if match else ""
    if db_name == PRODUCTION_DB_NAME:
        raise RuntimeError(
            f"TEST_DATABASE_URL points at the production database {PRODUCTION_DB_NAME!r}. "
            "Tests must use an isolated test database (e.g. storeye_test) so production "
            "data is never destroyed or modified."
        )
    return url


@pytest.fixture(scope="session", autouse=True)
def _guard_test_database():
    """Fail loudly if the test database is misconfigured (runs once/session)."""
    resolve_test_database_url()
    yield


@pytest.fixture(autouse=True)
def _reset_db(tmp_path, monkeypatch):
    """Reset the LEGACY SQLite diagnostics stack (app.core.database) between tests.

    This only affects the legacy SQLite/SQLModel stack exercised by the
    `/api/health`, `/api/ready`, `/api/metrics` endpoints and the
    `legacy_sqlite`-marked tests. The PostgreSQL business stack (app.db.session)
    is untouched by this fixture.
    """
    monkeypatch.setenv("EDGERETAIL_DATA_DIR", str(tmp_path))
    # Reset cached settings so new env var is picked up
    from app.core.config import get_settings
    get_settings.cache_clear()
    # Close any prior legacy engine/session
    import app.core.database as _db
    if _db._SessionLocal is not None:
        _db._SessionLocal.close()
        _db._SessionLocal = None
    if _db._engine is not None:
        _db._engine.dispose()
        _db._engine = None
    yield
    # Cleanup after test
    if _db._SessionLocal is not None:
        _db._SessionLocal.close()
        _db._SessionLocal = None
    if _db._engine is not None:
        _db._engine.dispose()
        _db._engine = None
    get_settings.cache_clear()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c

"""M22 — startup sequence and system readiness tests.

Split as required by the repository convention:

* ``no_db`` tests exercise configuration/strict-mode logic with no database.
* ``pg`` tests point DATABASE_URL at the isolated PostgreSQL test database and
  verify the runtime probe + ``/api/system/status`` endpoint.
"""

from __future__ import annotations

import os

import pytest

from app.core.config import get_settings
from app.core.startup import assess_runtime, expected_alembic_head

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://storeye@localhost:5433/storeye_test",
)


@pytest.fixture()
def clear_settings():
    before = {k: os.environ.get(k) for k in ("DATABASE_URL", "ENVIRONMENT", "STRICT_STARTUP")}
    get_settings.cache_clear()
    yield
    for k, v in before.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()


@pytest.mark.no_db
def test_alembic_head_is_known():
    assert expected_alembic_head() == "e7a3c5f1b2d8"


@pytest.mark.no_db
def test_missing_database_is_not_fatal_in_development(clear_settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    report = assess_runtime()
    assert report.database_configured is False
    assert report.fatal is False
    assert any("DATABASE_URL" in m for m in report.messages)


@pytest.mark.no_db
def test_missing_database_is_fatal_in_production(clear_settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    report = assess_runtime()
    assert report.fatal is True
    assert report.strict is True


@pytest.mark.pg
def test_runtime_probe_reaches_postgres(clear_settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    get_settings.cache_clear()
    report = assess_runtime(skip_in_tests=False)
    assert report.database_configured is True
    assert report.database_reachable is True
    assert report.migration_head == "e7a3c5f1b2d8"


@pytest.mark.pg
def test_system_status_endpoint(client, clear_settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    get_settings.cache_clear()
    r = client.get("/api/system/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["database"]["authoritative"] == "postgresql"
    assert body["database"]["reachable"] is True
    assert body["status"] in {"OK", "DEGRADED"}

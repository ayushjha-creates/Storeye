"""Alembic migration-chain verification against the isolated PostgreSQL test DB.

Runs the COMPLETE migration chain (base -> head) against a clean `storeye_test`
database and asserts the schema produced matches the expected head revision.
This proves Alembic — NOT `metadata.create_all` — can build the PostgreSQL
schema that the business/data layer depends on.

Chain (linear):
    4cafd848b801 (initial schema)
    -> c3a7600b329b (batches + batch_id on movements)
    -> e31098126b9c (AI observations)
    -> acf54c2aa5f9 (reconciliation results)
    -> b7f3d11e4a59 (products.ai_classes)
    -> d9e4a30f8b21 (alerts)
    -> c4f5a6b7c8d9 (products.barcode)                    <- head

Deliberately runs on the public schema of storeye_test only; it drops and
recreates that schema, so it can never touch the production `storeye` database
(the conftest test-database guard also forbids pointing at it).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import resolve_test_database_url

pytestmark = pytest.mark.pg

EXPECTED_HEAD = "c4f5a6b7c8d9"

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Tables that MUST exist once the full chain is applied.
EXPECTED_TABLES = {
    "stores",
    "users",
    "cameras",
    "zones",
    "shelves",
    "products",
    "customers",
    "inventory",
    "inventory_movements",
    "batches",
    "sales",
    "sale_items",
    "bills",
    "bill_items",
    "notifications",
    "observations",
    "reconciliation_results",
    "alerts",
    "planograms",
    "alembic_version",
}


@pytest.fixture(scope="session")
def db_url():
    return resolve_test_database_url()


@pytest.fixture(scope="session")
def clean_schema(db_url):
    """Drop + recreate the public schema so migrations start from a clean DB."""
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return db_url


def _run_alembic(db_url, command, revision):
    """Invoke `alembic <command> <revision>` against db_url in-process."""
    from alembic import command as alembic_command
    from alembic.config import Config

    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        getattr(alembic_command, command)(cfg, revision)
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old


def _list_tables(db_url):
    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
        ).fetchall()
    engine.dispose()
    return {r[0] for r in rows}


def _applied_head(db_url):
    engine = create_engine(db_url)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).fetchone()
    engine.dispose()
    return row[0] if row else None


def test_full_chain_upgrade_to_head(db_url, clean_schema):
    """Base -> head against a clean database produces the full schema."""
    _run_alembic(db_url, "upgrade", "head")

    assert _applied_head(db_url) == EXPECTED_HEAD, (
        f"alembic head mismatch (expected {EXPECTED_HEAD})"
    )

    tables = _list_tables(db_url)
    missing = EXPECTED_TABLES - tables
    assert not missing, f"migration chain is missing tables: {sorted(missing)}"


def test_down_base_then_reupgrade_chain(db_url, clean_schema):
    """The chain is repeatable from a clean base (downgrade base -> upgrade head)."""
    _run_alembic(db_url, "upgrade", "head")
    assert _applied_head(db_url) == EXPECTED_HEAD

    _run_alembic(db_url, "downgrade", "base")
    assert _applied_head(db_url) is None, "downgrade base should remove alembic_version"
    # Alembic leaves the (empty) alembic_version table behind after downgrade base.
    remaining = _list_tables(db_url) - {"alembic_version"}
    assert remaining == set(), f"downgrade base should empty the schema, got: {sorted(remaining)}"

    _run_alembic(db_url, "upgrade", "head")
    tables = _list_tables(db_url)
    missing = EXPECTED_TABLES - tables
    assert not missing, f"re-upgrade is missing tables: {sorted(missing)}"
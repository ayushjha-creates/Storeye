"""Database engine/session management for Storeye (PostgreSQL).

Credentials come exclusively from the DATABASE_URL environment variable.
No credentials are hard-coded. For tests, an isolated DATABASE_URL is
used so production data is never touched.
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from .base import Base

logger = logging.getLogger("storeye.db")

engine: Engine | None = None
SessionLocal: sessionmaker | None = None


def get_database_url() -> str:
    """Return the DATABASE_URL, raising a clear error if absent."""
    url = get_settings().DATABASE_URL
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured. "
            "Set it in the environment or in backend/.env "
            "(see .env.example)."
        )
    return url


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create (and return) a new SQLAlchemy engine from DATABASE_URL."""
    url = database_url or get_database_url()
    return create_engine(url, pool_pre_ping=True, future=True)


def init_engine(database_url: str | None = None) -> Engine:
    """Create the global engine + sessionmaker once, and return the engine."""
    global engine, SessionLocal
    if engine is None:
        engine = create_db_engine(database_url)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        logger.info("Database engine initialised")
    return engine


def get_session() -> Session:
    """Return a new Session tied to the global engine."""
    if SessionLocal is None:
        init_engine()
    assert SessionLocal is not None
    return SessionLocal()


def create_tables(engine_: Engine) -> None:
    """Create all tables (used for tests / quick bootstrap, not prod)."""
    Base.metadata.create_all(engine_)


def drop_tables(engine_: Engine) -> None:
    """Drop all tables (tests only)."""
    Base.metadata.drop_all(engine_)


def dispose_engine() -> None:
    global engine, SessionLocal
    if engine is not None:
        engine.dispose()
    engine = None
    SessionLocal = None
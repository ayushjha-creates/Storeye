"""FastAPI dependencies — inject SQLAlchemy sessions into routers.

Routers depend on `get_db()` (or, for tests, an overridden equivalent) to
obtain a transactional Session. Sessions come from the PostgreSQL stack in
app.db.session; the legacy SQLite/SQLModel stack (app.core.database) is NOT
used here.

Each request gets a fresh Session which is closed when the request ends.
Writes are committed by the underlying domain services; uncommitted dirty
state is rolled back defensively on error.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..db.session import get_session


def get_db() -> Iterator[Session]:
    """Yield a SQLAlchemy Session for the lifetime of one request."""
    session: Session = get_session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

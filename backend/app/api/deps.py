"""FastAPI dependencies — SQLAlchemy sessions + authentication.

Routers depend on `get_db()` (or, for tests, an overridden equivalent) to
obtain a transactional Session. Sessions come from the PostgreSQL stack in
app.db.session; the legacy SQLite/SQLModel stack (app.core.database) is NOT
used here.

Authentication is cookie/session based:

    get_current_session  -> resolves the HttpOnly session cookie to its row
    get_current_user     -> the User owning that session (must be active)
    get_current_active_user -> alias kept for readability
    require_role(...)    -> role-gated dependency (RBAC)
    require_csrf         -> rejects state-changing requests without the header

Each request gets a fresh Session which is closed when the request ends.
Writes are committed by the underlying domain services; uncommitted dirty
state is rolled back defensively on error.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core.auth import role_level
from ..core.config import get_settings
from ..models import AuthSession, User
from ..services.auth_service import get_session_by_token, is_session_active
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


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_current_session(
    request: Request, db: Session = Depends(get_db)
) -> AuthSession:
    """Resolve the HttpOnly session cookie to a valid session row."""
    settings = get_settings()
    raw_secret = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not raw_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    auth_session = get_session_by_token(db, raw_secret)
    if auth_session is None or not is_session_active(auth_session):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or revoked",
        )
    return auth_session


def get_current_user(
    auth_session: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> User:
    """Return the active User owning the current session."""
    user = db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


def require_role(min_role: str):
    """Dependency factory requiring the authenticated role >= `min_role`."""

    def _dep(current_user: User = Depends(get_current_active_user)) -> User:
        if role_level(current_user.role) < role_level(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this operation",
            )
        return current_user

    return _dep


def require_csrf(request: Request) -> None:
    """Reject state-changing requests missing the custom CSRF header.

    Cross-site forms cannot set custom headers; the Storeye frontend client
    always sends `X-Storeye-CSRF: 1` on non-GET requests. Combined with
    SameSite=Lax cookies and the strict local CORS allow-list this is a
    practical CSRF control for an offline edge web app.
    """
    settings = get_settings()
    expected = settings.AUTH_CSRF_VALUE
    provided = request.headers.get(settings.AUTH_CSRF_HEADER)
    if not expected or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or invalid CSRF header",
        )
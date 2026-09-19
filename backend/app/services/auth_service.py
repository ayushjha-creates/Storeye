"""Authentication service: sessions, login, logout, password change.

Design:
- Session secrets are 32-byte cryptographically-random values issued once, at
  login, as an HttpOnly cookie. Only their SHA-256 hash is ever persisted.
- Sessions are revocable (logout / logout-all / password change) and expire
  after `AUTH_SESSION_TTL_HOURS`.
- Login is throttled in-process to blunt brute forcing (a local app: the
  throttle is per identity, in memory, and resets after the window elapses).
"""

from __future__ import annotations

import hashlib
import secrets
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..core.auth import hash_password, verify_password, redact
from ..core.config import get_settings
from ..models import AuthSession, User


def hash_token(raw_secret: str) -> str:
    """SHA-256 hex digest of a raw session secret (never stored raw)."""
    return hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()


def generate_secret() -> str:
    """Cryptographically secure random session secret."""
    return secrets.token_urlsafe(32)


def create_session(
    db: Session,
    user_id,
    *,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> tuple[str, AuthSession]:
    """Create a session row (hash only) and return (raw_secret, row)."""
    settings = get_settings()
    raw_secret = generate_secret()
    session = AuthSession(
        user_id=user_id,
        token_hash=hash_token(raw_secret),
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.AUTH_SESSION_TTL_HOURS),
        user_agent=(user_agent or "")[:512] or None,
        ip_address=(ip_address or "")[:64] or None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return raw_secret, session


def get_session_by_token(db: Session, raw_secret: str) -> Optional[AuthSession]:
    """Resolve a raw cookie secret to its session row (hash lookup)."""
    return db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_token(raw_secret))
    )


def is_session_active(auth_session: AuthSession, now: Optional[datetime] = None) -> bool:
    """A session is active if not revoked and not past expires_at."""
    now = now or datetime.now(timezone.utc)
    if auth_session.revoked_at is not None:
        return False
    if auth_session.expires_at is not None and auth_session.expires_at <= now:
        return False
    return True


def revoke_session(db: Session, auth_session: AuthSession) -> None:
    """Revoke a single session (normal logout / password-change current session)."""
    if auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now(timezone.utc)
        db.add(auth_session)
        db.commit()


def revoke_all_user_sessions(
    db: Session, user_id, *, except_session_id=None
) -> int:
    """Revoke every active session for a user. Optionally keep one session."""
    now = datetime.now(timezone.utc)
    stmt = update(AuthSession).where(
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
    )
    if except_session_id is not None:
        stmt = stmt.where(AuthSession.id != except_session_id)
    stmt = stmt.values(revoked_at=now)
    res = db.execute(stmt)
    db.commit()
    return res.rowcount or 0


def authenticate(
    db: Session, email: str, password: str
) -> Optional[User]:
    """Verify credentials. Returns the user on success, None otherwise.

    Always returns None with a generic message for unknown email, wrong
    password, or inactive account so callers never leak account existence.
    """
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if user is None:
        return None
    if not user.is_active:
        return None
    if not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    return user


# ---------------------------------------------------------------------------
# Login throttling (in-memory, per identity). Local edge deployment: this is a
# practical brute-force brake, not a distributed IAM mechanism.
# ---------------------------------------------------------------------------

_throttle_lock = threading.Lock()
# identity -> (first_failure_at_epoch, failure_count)
_failures: dict[str, list] = {}


def _throttle_key(email: str, ip: str | None) -> str:
    return f"{email.lower().strip()}::{ip or '?'}"


def login_throttled(email: str, ip: str | None) -> bool:
    settings = get_settings()
    window = settings.AUTH_LOGIN_THROTTLE_SECONDS
    now = time.monotonic()
    with _throttle_lock:
        key = _throttle_key(email, ip)
        entry = _failures.get(key)
        if entry is None:
            return False
        first_failure, count = entry
        if now - first_failure > window:
            _failures.pop(key, None)
            return False
        return count >= settings.AUTH_LOGIN_MAX_ATTEMPTS


def record_login_failure(email: str, ip: str | None) -> None:
    settings = get_settings()
    window = settings.AUTH_LOGIN_THROTTLE_SECONDS
    now = time.monotonic()
    with _throttle_lock:
        key = _throttle_key(email, ip)
        entry = _failures.get(key)
        if entry is None or now - entry[0] > window:
            _failures[key] = [now, 1]
        else:
            entry[1] += 1


def reset_login_failures(email: str, ip: str | None) -> None:
    with _throttle_lock:
        _failures.pop(_throttle_key(email, ip), None)


def change_password(
    db: Session,
    user: User,
    current_password: str,
    new_password: str,
    *,
    current_session_id=None,
    revoke_others: bool = True,
) -> int:
    """Change a user's password and revoke all other sessions.

    Returns the number of sessions revoked (excluding the current session when
    `current_session_id` is given and `revoke_others` is True).
    """
    if user.password_hash and not verify_password(current_password, user.password_hash):
        raise ValueError("Current password is incorrect")
    user.password_hash = hash_password(new_password)
    db.add(user)
    db.commit()
    revoked = 0
    if revoke_others:
        revoked = revoke_all_user_sessions(
            db, user.id, except_session_id=current_session_id
        )
    return revoked


# Convenience alias for controlled logging.
def describe_secret(value: str | None) -> str:
    return redact(value)
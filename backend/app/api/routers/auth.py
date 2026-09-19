"""Authentication API routes.

Session-cookie authentication against the local PostgreSQL deployment.

    POST /api/auth/login           -> verify Argon2id, set HttpOnly cookie
    POST /api/auth/logout          -> revoke the current session, clear cookie
    GET  /api/auth/me              -> sanitized current user (+ store info)
    POST /api/auth/change-password -> rotate password, revoke other sessions
    POST /api/auth/logout-all      -> revoke every session for the user

There is intentionally NO public registration endpoint: Storeye is provisioned
by an OWNER through POST /api/users (or the seed scripts). Login failures use a
generic message so an account's existence is not discoverable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..deps import (
    get_current_session,
    get_current_user,
    get_db,
    require_csrf,
)
from ...core.auth import password_is_valid
from ...core.config import get_settings
from ...models import AuthSession, Store, User
from ...schemas import (
    AuthUserRead,
    ChangePasswordIn,
    LoginIn,
    LoginResponse,
    MessageOut,
)
from ...services.auth_service import (
    authenticate,
    change_password,
    create_session,
    login_throttled,
    record_login_failure,
    reset_login_failures,
    revoke_all_user_sessions,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Invalid email or password"


def _set_session_cookie(response: Response, raw_secret: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=raw_secret,
        max_age=int(settings.AUTH_SESSION_TTL_HOURS * 3600),
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        samesite=settings.AUTH_COOKIE_SAMESITE,
        secure=settings.AUTH_COOKIE_SECURE,
    )


def _client_ip(request: Request) -> Optional[str]:
    # FastAPI/uvicorn populates client only when the app runs behind a proxy in
    # some setups; falling back to host from the request scope keeps it safe.
    client = request.client
    if client is not None:
        return client.host
    return None


def _to_auth_user(db: Session, user: User) -> AuthUserRead:
    store = db.get(Store, user.store_id)
    return AuthUserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        store_id=user.store_id,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        store_name=store.name if store else None,
        demo_store=bool(store.is_demo) if store else False,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> LoginResponse:
    ip = _client_ip(request)
    email = payload.email.strip().lower()
    if login_throttled(email, ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )

    user = authenticate(db, email, payload.password)
    if user is None:
        record_login_failure(email, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GENERIC_LOGIN_ERROR,
        )
    reset_login_failures(email, ip)

    raw_secret, _session = create_session(
        db,
        user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=ip,
    )
    settings = get_settings()
    _set_session_cookie(response, raw_secret)
    return LoginResponse(
        user=_to_auth_user(db, user),
        expires_in_seconds=int(settings.AUTH_SESSION_TTL_HOURS * 3600),
    )


@router.post("/logout", response_model=MessageOut)
def logout(
    response: Response,
    auth_session: AuthSession = Depends(get_current_session),
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> MessageOut:
    revoke_session(db, auth_session)
    _clear_session_cookie(response)
    return MessageOut(message="Signed out")


@router.get("/me", response_model=AuthUserRead)
def me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthUserRead:
    return _to_auth_user(db, current_user)


@router.post("/change-password", response_model=MessageOut)
def change_password_endpoint(
    payload: ChangePasswordIn,
    response: Response,
    current_user: User = Depends(get_current_user),
    auth_session: AuthSession = Depends(get_current_session),
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> MessageOut:
    if payload.new_password != payload.new_password_confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password confirmation does not match",
        )
    if not password_is_valid(payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be at least 8 characters",
        )
    try:
        revoked = change_password(
            db,
            current_user,
            payload.current_password,
            payload.new_password,
            current_session_id=auth_session.id,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    # The current session stays alive (UX-friendly). Update the expiry/last seen
    # so the just-authenticated session behaves normally.
    auth_session.last_seen_at = datetime.now(timezone.utc)
    db.add(auth_session)
    db.commit()
    return MessageOut(message=f"Password updated ({revoked} other session(s) revoked)")


@router.post("/logout-all", response_model=MessageOut)
def logout_all(
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> MessageOut:
    revoked = revoke_all_user_sessions(db, current_user.id)
    return MessageOut(message=f"All sessions signed out ({revoked} revoked)")
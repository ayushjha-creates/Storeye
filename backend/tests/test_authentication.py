"""End-to-end authentication & authorization tests (real PostgreSQL).

Exercises the real login/session/logout/password-change flow through the HTTP
surface, plus the store-isolation and RBAC boundaries every business router now
enforces. Uses a real `storeye_test` database so session rows, Argon2id hashes
and role checks are all genuinely persisted and validated.

Scenarios covered:
  * Argon2id hashing round-trip + password policy + role aliases
  * login success (HttpOnly cookie, sanitized body, no password_hash)
  * generic failure for wrong password / unknown email / inactive account
  * CSRF header required on auth mutations
  * /me requires a valid session; returns sanitized user
  * session expiry + explicit revocation are both rejected
  * logout clears the cookie and revokes the row
  * logout-all revokes every session for the user
  * change-password verifies the current password and revokes other sessions
  * login throttle after repeated failures
  * cross-store reads 404 / cross-store store_id 403
  * RBAC: STAFF cannot mutate manager-only resources; legacy alias authorizes
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_db
from app.core.auth import (
    canonical_role,
    hash_password,
    password_is_valid,
    role_at_least,
    role_level,
    verify_password,
)
from app.db.base import Base
from app.main import app
from app.models import AuthSession, Product, Store, User
from app.services.auth_service import hash_token

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://storeye@localhost:5433/storeye_test",
)

CSRF = {"X-Storeye-CSRF": "1"}
PASSWORD = "StoreyePass@123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(TEST_DB_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """The login throttle is process-global; isolate tests from each other."""
    from app.services import auth_service

    auth_service._failures.clear()
    yield
    auth_service._failures.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    session_factory,
    *,
    password: str = PASSWORD,
    role: str = "OWNER",
    email: str | None = None,
    active: bool = True,
    store_name: str = "Auth Store",
    store_is_demo: bool = False,
):
    """Create a store + user directly in the test DB; return identifiers."""
    email = email or f"user-{uuid4().hex[:10]}@storeye.local"
    session = session_factory()
    try:
        store = Store(name=store_name, timezone="Asia/Kolkata", is_demo=store_is_demo)
        session.add(store)
        session.flush()
        user = User(
            store_id=store.id,
            name="Auth User",
            role=role,
            email=email,
            is_active=active,
            password_hash=hash_password(password) if password else None,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return SimpleNamespace(
            user_id=user.id,
            store_id=store.id,
            email=email,
            password=password,
            role=role,
        )
    finally:
        session.close()


def _login(client, email: str, password: str, *, csrf: bool = True):
    headers = dict(CSRF) if csrf else {}
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers=headers,
    )


def _cookie_value(client) -> str:
    from app.core.config import get_settings

    return client.cookies.get(get_settings().AUTH_COOKIE_NAME)


def _session_row(session_factory, raw_secret: str) -> AuthSession:
    session = session_factory()
    try:
        row = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_token(raw_secret))
        )
        assert row is not None
        session.expunge(row)
        return row
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Primitives (no HTTP)
# ---------------------------------------------------------------------------


def test_password_hash_roundtrip_and_policy():
    h = hash_password(PASSWORD)
    assert h != PASSWORD
    assert h.startswith("$argon2id$")
    assert verify_password(PASSWORD, h) is True
    assert verify_password("wrong-password", h) is False
    assert password_is_valid("longenough") is True
    assert password_is_valid("short") is False


def test_role_levels_and_legacy_aliases():
    assert role_level("OWNER") > role_level("MANAGER") > role_level("STAFF") > 0
    assert role_at_least("MANAGER", "STAFF") is True
    assert role_at_least("STAFF", "MANAGER") is False
    # Legacy strings resolve for authorization and canonicalize on write.
    assert role_level("ASSOCIATE") == role_level("STAFF")
    assert role_level("Store Manager") == role_level("MANAGER")
    assert canonical_role("ASSOCIATE") == "STAFF"
    assert canonical_role("REGIONAL_ADMIN") == "OWNER"
    assert canonical_role("nonsense") == "STAFF"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_success_sets_httponly_cookie_and_sanitized_body(client, session_factory):
    u = _make_user(session_factory, role="OWNER")
    r = _login(client, u.email, u.password)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == u.email
    assert body["user"]["role"] == "OWNER"
    assert body["user"]["store_id"] == str(u.store_id)
    assert body["user"]["store_name"] == "Auth Store"
    assert "password_hash" not in body["user"]
    assert body["expires_in_seconds"] > 0

    set_cookie = r.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "storeye_session=" in set_cookie


def test_login_requires_csrf_header(client, session_factory):
    u = _make_user(session_factory)
    r = _login(client, u.email, u.password, csrf=False)
    assert r.status_code == 403


def test_login_wrong_password_is_generic_401(client, session_factory):
    u = _make_user(session_factory)
    r = _login(client, u.email, "not-the-password")
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_login_unknown_email_is_generic_401(client, session_factory):
    r = _login(client, "nobody@storeye.local", PASSWORD)
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_login_inactive_account_rejected(client, session_factory):
    u = _make_user(session_factory, active=False)
    r = _login(client, u.email, u.password)
    assert r.status_code == 401


def test_login_throttle_after_repeated_failures(client, session_factory):
    u = _make_user(session_factory)
    for _ in range(8):
        assert _login(client, u.email, "wrong").status_code == 401
    # The next attempt is throttled even with the correct password.
    r = _login(client, u.email, u.password)
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# /me + session validity
# ---------------------------------------------------------------------------


def test_me_without_session_is_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_sanitized_user(client, session_factory):
    u = _make_user(session_factory, role="MANAGER")
    assert _login(client, u.email, u.password).status_code == 200
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == u.email
    assert "password_hash" not in r.json()


def test_expired_session_is_rejected(client, session_factory):
    u = _make_user(session_factory)
    assert _login(client, u.email, u.password).status_code == 200
    raw = _cookie_value(client)

    session = session_factory()
    try:
        row = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_token(raw))
        )
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        session.add(row)
        session.commit()
    finally:
        session.close()

    assert client.get("/api/auth/me").status_code == 401


def test_revoked_session_is_rejected(client, session_factory):
    u = _make_user(session_factory)
    assert _login(client, u.email, u.password).status_code == 200
    raw = _cookie_value(client)

    session = session_factory()
    try:
        row = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_token(raw))
        )
        row.revoked_at = datetime.now(timezone.utc)
        session.add(row)
        session.commit()
    finally:
        session.close()

    assert client.get("/api/auth/me").status_code == 401


# ---------------------------------------------------------------------------
# Logout / logout-all
# ---------------------------------------------------------------------------


def test_logout_revokes_session_and_clears_cookie(client, session_factory):
    u = _make_user(session_factory)
    assert _login(client, u.email, u.password).status_code == 200
    raw = _cookie_value(client)

    r = client.post("/api/auth/logout", headers=CSRF)
    assert r.status_code == 200
    # Server-side session row is revoked...
    assert _session_row(session_factory, raw).revoked_at is not None
    # ...and the cookie no longer authenticates.
    assert client.get("/api/auth/me").status_code == 401


def test_logout_requires_csrf(client, session_factory):
    u = _make_user(session_factory)
    assert _login(client, u.email, u.password).status_code == 200
    assert client.post("/api/auth/logout").status_code == 403


def test_logout_all_revokes_every_session(client, session_factory):
    u = _make_user(session_factory)
    assert _login(client, u.email, u.password).status_code == 200

    second = TestClient(app)
    try:
        assert _login(second, u.email, u.password).status_code == 200
        assert second.get("/api/auth/me").status_code == 200

        r = client.post("/api/auth/logout-all", headers=CSRF)
        assert r.status_code == 200

        assert client.get("/api/auth/me").status_code == 401
        assert second.get("/api/auth/me").status_code == 401
    finally:
        second.close()


# ---------------------------------------------------------------------------
# change-password
# ---------------------------------------------------------------------------


def test_change_password_verifies_current_and_revokes_others(client, session_factory):
    u = _make_user(session_factory)
    assert _login(client, u.email, u.password).status_code == 200

    second = TestClient(app)
    try:
        assert _login(second, u.email, u.password).status_code == 200

        r = client.post(
            "/api/auth/change-password",
            json={
                "current_password": u.password,
                "new_password": "BrandNewPass@456",
                "new_password_confirm": "BrandNewPass@456",
            },
            headers=CSRF,
        )
        assert r.status_code == 200, r.text

        # Current session survives; the other is revoked.
        assert client.get("/api/auth/me").status_code == 200
        assert second.get("/api/auth/me").status_code == 401

        # Old password no longer authenticates; the new one does.
        assert _login(client, u.email, u.password).status_code == 401
        assert _login(client, u.email, "BrandNewPass@456").status_code == 200
    finally:
        second.close()


def test_change_password_rejects_wrong_current(client, session_factory):
    u = _make_user(session_factory)
    assert _login(client, u.email, u.password).status_code == 200
    r = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "wrong-current",
            "new_password": "BrandNewPass@456",
            "new_password_confirm": "BrandNewPass@456",
        },
        headers=CSRF,
    )
    assert r.status_code == 401


def test_change_password_rejects_mismatched_confirmation(client, session_factory):
    u = _make_user(session_factory)
    assert _login(client, u.email, u.password).status_code == 200
    r = client.post(
        "/api/auth/change-password",
        json={
            "current_password": u.password,
            "new_password": "BrandNewPass@456",
            "new_password_confirm": "DifferentPass@789",
        },
        headers=CSRF,
    )
    assert r.status_code == 422


def test_change_password_requires_csrf(client, session_factory):
    u = _make_user(session_factory)
    assert _login(client, u.email, u.password).status_code == 200
    r = client.post(
        "/api/auth/change-password",
        json={
            "current_password": u.password,
            "new_password": "BrandNewPass@456",
            "new_password_confirm": "BrandNewPass@456",
        },
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Store isolation
# ---------------------------------------------------------------------------


def test_cross_store_resource_read_is_404(client, session_factory):
    a = _make_user(session_factory, store_name="Store A")
    b = _make_user(session_factory, store_name="Store B")

    session = session_factory()
    try:
        product = Product(store_id=b.store_id, sku="B-1", name="B Product", selling_price=5)
        session.add(product)
        session.commit()
        product_id = str(product.id)
    finally:
        session.close()

    assert _login(client, a.email, a.password).status_code == 200
    # Another store's row is indistinguishable from missing.
    assert client.get(f"/api/products/{product_id}").status_code == 404


def test_cross_store_query_parameter_is_403(client, session_factory):
    a = _make_user(session_factory, store_name="Store A")
    b = _make_user(session_factory, store_name="Store B")
    assert _login(client, a.email, a.password).status_code == 200
    r = client.get(f"/api/products?store_id={b.store_id}")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_staff_can_read_but_not_create_products(client, session_factory):
    u = _make_user(session_factory, role="STAFF")
    assert _login(client, u.email, u.password).status_code == 200

    assert client.get("/api/products").status_code == 200
    r = client.post(
        "/api/products",
        json={
            "store_id": str(u.store_id),
            "sku": "S-1",
            "name": "Staff Product",
            "selling_price": "9.99",
        },
    )
    assert r.status_code == 403


def test_legacy_associate_role_authorizes_as_staff(client, session_factory):
    u = _make_user(session_factory, role="ASSOCIATE")
    assert _login(client, u.email, u.password).status_code == 200
    # STAFF-floor read is allowed; manager-only write is not.
    assert client.get("/api/products").status_code == 200
    r = client.post(
        "/api/products",
        json={
            "store_id": str(u.store_id),
            "sku": "S-2",
            "name": "Legacy Product",
            "selling_price": "1.00",
        },
    )
    assert r.status_code == 403


def test_unauthenticated_business_endpoint_is_401(client):
    assert client.get("/api/products").status_code == 401

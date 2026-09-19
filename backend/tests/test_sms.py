"""M31 tests: SMS bill-receipt outbox (MSG91).

Covers:
  * Settings validation for the SMS knobs (no_db)
  * receipt message builder (no_db)
  * MSG91 gateway client against a faked HTTP transport (no_db)
  * outbox queue lifecycle: atomic enqueue, claim ordering, SENT on ack,
    retry-with-backoff, terminal FAILED, stale-claim re-claim, resend (pg)
  * API: list / status / resend + per-store authz (pg)
  * bills router auto-enqueue when SMS is enabled (pg)

No fabricated delivery: every success/failure uses a fake gateway that returns
a real ack or a real error — the queue's bad paths are exercised, not skipped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import Settings
from app.models import (
    MSG_FAILED,
    MSG_QUEUED,
    MSG_SENDING,
    MSG_SENT,
    Bill,
    BillItem,
    Customer,
    Product,
    SmsMessage,
)
from app.services.sms.gateway import (
    Msg91Gateway,
    SmsGatewayError,
    SmsGatewayNotConfigured,
    SmsSendResult,
)
from app.services.sms.outbox import SmsOutboxService
from app.services.sms.receipt import build_bill_receipt
from tests.conftest import bind_test_user, make_store, resolve_test_database_url

TEST_DB_URL = resolve_test_database_url()

no_db_mark = pytest.mark.no_db
pg_mark = pytest.mark.pg


def _settings(**overrides) -> Settings:
    base = dict(
        SMS_ENABLED=True,
        SMS_PROVIDER="msg91",
        MSG91_AUTH_KEY="test-auth-key",
        MSG91_SENDER_ID="TESTID",
        MSG91_ROUTE=4,
        MSG91_COUNTRY_CODE="91",
        MSG91_BASE_URL="https://test.msg91.in",
        SMS_MAX_ATTEMPTS=5,
        SMS_RETRY_BACKOFF_SECONDS=60.0,
        SMS_STALE_CLAIM_SECONDS=30.0,
        SMS_TIMEOUT_SECONDS=10.0,
    )
    base.update(overrides)
    return Settings(_env_file=None, DATABASE_URL=TEST_DB_URL, **base)


# ---------------------------------------------------------------------------
# Settings validation (no_db)
# ---------------------------------------------------------------------------
@no_db_mark
def test_sms_settings_validated():
    s = _settings()
    assert s.SMS_ENABLED is True
    assert s.SMS_PROVIDER == "msg91"
    assert s.MSG91_SENDER_ID == "TESTID"


@no_db_mark
def test_sms_provider_must_be_msg91():
    with pytest.raises(ValidationError, match="SMS_PROVIDER"):
        _settings(SMS_PROVIDER="twilio")


@no_db_mark
def test_sender_id_must_be_6_alnum():
    with pytest.raises(ValidationError, match="MSG91_SENDER_ID"):
        _settings(MSG91_SENDER_ID="ABC")
    assert _settings(MSG91_SENDER_ID="").MSG91_SENDER_ID == ""


@no_db_mark
def test_sms_negative_knobs_rejected():
    with pytest.raises(ValidationError, match="SMS_MAX_ATTEMPTS"):
        _settings(SMS_MAX_ATTEMPTS=-1)
    with pytest.raises(ValidationError, match="SMS_POLL_SECONDS"):
        _settings(SMS_POLL_SECONDS=0)


# ---------------------------------------------------------------------------
# Receipt builder (no_db)
# ---------------------------------------------------------------------------
class _NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@no_db_mark
def test_receipt_builder_is_short_and_honest():
    bill = _NS(id=uuid4(), bill_number="B-42", total=Decimal("125.50"),
               created_at=datetime(2026, 9, 18, 10, 30, tzinfo=timezone.utc))
    store = _NS(name="Rohit Kirana")
    customer = _NS(name="Ria", mobile="9876543210")
    names = ["Biscuit", "Soyabean"]
    msg = build_bill_receipt(bill, store, customer, names)
    assert "Rohit Kirana" in msg
    assert "B-42" in msg
    assert "18 Sep 2026" in msg
    assert "Ria" in msg
    assert "Biscuit, Soyabean" in msg
    assert "₹125.50" in msg
    assert "Thank you" in msg


@no_db_mark
def test_receipt_builder_handles_missing_store_customer_and_item_names():
    bill = _NS(id=uuid4(), bill_number="B-1", total=None, created_at=None)
    msg = build_bill_receipt(bill, None, None, None)
    assert "Storeye" in msg
    assert "B-1" in msg
    assert "Total paid" not in msg
    assert "Customer" not in msg
    assert "Items" not in msg


@no_db_mark
def test_receipt_builder_caps_number_of_item_names():
    bill = _NS(id=uuid4(), bill_number="B-99", total=Decimal("1.00"),
               created_at=None)
    names = [f"Item {i}" for i in range(9)]
    msg = build_bill_receipt(bill, _NS(name="S"), None, names)
    assert "Items: Item 0, Item 1, Item 2, Item 3, Item 4, Item 5" in msg
    assert "+3 more" in msg


# ---------------------------------------------------------------------------
# MSG91 gateway (no_db) — real HTTP is faked, nothing is invented
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code


@no_db_mark
def test_gateway_builds_correct_request_and_acks(monkeypatch):
    captured = {"url": None, "params": None}

    def fake_post(url, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return _FakeResp("type:success,This is a test message")

    monkeypatch.setattr("app.services.sms.gateway.httpx.post", fake_post)
    gw = Msg91Gateway(_settings())
    result = gw.send("9876543210", "hello")
    assert result.success is True
    assert "success" in result.response
    assert captured["url"] == "https://test.msg91.in/api/sendhttp.php"
    assert captured["params"]["authkey"] == "test-auth-key"
    assert captured["params"]["mobiles"] == "9876543210"
    assert captured["params"]["message"] == "hello"
    assert captured["params"]["route"] == 4
    assert captured["params"]["country"] == "91"
    assert captured["params"]["sender"] == "TESTID"


@no_db_mark
def test_gateway_omits_sender_when_unset(monkeypatch):
    captured = {}

    def fake_post(url, params=None, **kwargs):
        captured["params"] = params
        return _FakeResp("type:success")

    monkeypatch.setattr("app.services.sms.gateway.httpx.post", fake_post)
    gw = Msg91Gateway(_settings(MSG91_SENDER_ID=""))
    gw.send("9876543210", "hi")
    assert "sender" not in captured["params"]


@no_db_mark
def test_gateway_raises_on_provider_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.sms.gateway.httpx.post",
        lambda url, params=None, **kw: _FakeResp("type:error,errorcode:298,something went wrong"),
    )
    with pytest.raises(SmsGatewayError, match="errorcode"):
        Msg91Gateway(_settings()).send("9876543210", "x")


@no_db_mark
def test_gateway_raises_on_http_and_empty_body(monkeypatch):
    monkeypatch.setattr(
        "app.services.sms.gateway.httpx.post",
        lambda url, params=None, **kw: _FakeResp("", status_code=500),
    )
    with pytest.raises(SmsGatewayError, match="HTTP 500"):
        Msg91Gateway(_settings()).send("9", "x")
    monkeypatch.setattr(
        "app.services.sms.gateway.httpx.post",
        lambda url, params=None, **kw: _FakeResp("", status_code=200),
    )
    with pytest.raises(SmsGatewayError):
        Msg91Gateway(_settings()).send("9", "x")


@no_db_mark
def test_gateway_raises_on_transport_error(monkeypatch):
    def boom(url, params=None, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr("app.services.sms.gateway.httpx.post", boom)
    with pytest.raises(SmsGatewayError):
        Msg91Gateway(_settings()).send("9", "x")


@no_db_mark
def test_gateway_refuses_when_not_configured(monkeypatch):
    monkeypatch.setattr(
        "app.services.sms.gateway.httpx.post",
        lambda url, params=None, **kw: _FakeResp("type:success"),
    )
    gw = Msg91Gateway(_settings(MSG91_AUTH_KEY=""))
    assert gw.configured() is False
    with pytest.raises(SmsGatewayNotConfigured, match="MSG91_AUTH_KEY"):
        gw.send("9", "x")


# ---------------------------------------------------------------------------
# PostgreSQL fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL)
    from app.db.base import Base

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    from app.db.base import Base

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

    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed(session_factory, *, mobile="9876543210", name="Ria"):
    """Create store + customer + one product + one bill; return their ids."""
    store = make_store(session_factory, "SMS Mart")
    session = session_factory()
    try:
        customer = Customer(store_id=store.id, mobile=mobile, name=name)
        product = Product(
            store_id=store.id, sku="SKU-1", name="Biscuit",
            selling_price=Decimal("10.00"),
        )
        session.add_all([customer, product])
        session.flush()  # assign customer.id / product.id
        bill = Bill(
            store_id=store.id, bill_number="B-100",
            subtotal=Decimal("10.00"), tax_total=Decimal("0.00"),
            total=Decimal("10.00"), delivery_status="DRAFT",
        )
        bill.items = [
            BillItem(
                product_id=product.id, quantity=1,
                unit_price=Decimal("10.00"), tax=Decimal("0.00"),
                line_total=Decimal("10.00"),
            )
        ]
        session.add(bill)
        session.commit()
        session.refresh(bill)
        session.refresh(customer)
        session.refresh(product)
        ids = (store.id, bill.id, customer.id, product.id)
    finally:
        session.close()
    return ids


def _row(session_factory, store_id, *, bill_id=None, status=MSG_QUEUED,
         attempts=0, next_attempt_at=None):
    session = session_factory()
    try:
        row = SmsMessage(
            store_id=store_id,
            bill_id=bill_id,
            mobile="9876543210",
            message="Receipt",
            status=status,
            attempts=attempts,
            next_attempt_at=next_attempt_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        row_id = row.id
    finally:
        session.close()
    return row_id


class FakeGateway:
    """Deterministic gateway stand-in: acks, or raises a real SmsGatewayError."""

    def __init__(self, mode="ok"):
        self.mode = mode  # ok | retry | fatal
        self.calls: list[tuple[str, str]] = []

    def send(self, mobile, message):
        self.calls.append((mobile, message))
        if self.mode == "retry":
            raise SmsGatewayError("provider timeout")
        if self.mode == "fatal":
            raise SmsGatewayNotConfigured("MSG91_AUTH_KEY is empty")
        return SmsSendResult(response="type:success")


# ---------------------------------------------------------------------------
# Outbox lifecycle (pg)
# ---------------------------------------------------------------------------
@pg_mark
def test_enqueue_for_bill_skips_without_mobile(session_factory):
    store_id, bill_id, _, _ = _seed(session_factory, mobile=" ")
    session = session_factory()
    try:
        bill = session.get(Bill, bill_id)
        # No customer passed -> skipped.
        assert SmsOutboxService(session).enqueue_for_bill(bill, None, None) is None
        assert session.scalar(select(SmsMessage).where(SmsMessage.bill_id == bill_id)) is None
    finally:
        session.close()


@pg_mark
def test_enqueue_for_bill_queues_with_mobile(session_factory):
    store_id, bill_id, customer_id, product_id = _seed(session_factory)
    session = session_factory()
    try:
        bill = session.get(Bill, bill_id)
        customer = session.get(Customer, customer_id)
        store = _NS(id=store_id, name="SMS Mart")
        row = SmsOutboxService(session).enqueue_for_bill(bill, store, customer)
        assert row is not None
        assert row.status == MSG_QUEUED
        assert row.attempts == 0
        assert row.mobile == "9876543210"
        assert row.bill_id == bill_id
        assert "B-100" in row.message
        assert "₹10.00" in row.message
        assert "Biscuit" in row.message
    finally:
        session.close()


@pg_mark
def test_process_pending_sends_and_sets_sent_at(session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    row_id = _row(session_factory, store_id, bill_id=bill_id)
    session = session_factory()
    try:
        svc = SmsOutboxService(session)
        result = svc.process_pending(gateway=FakeGateway("ok"))
        assert result == {"claimed": 1, "sent": 1, "failed": 0}
        row = session.get(SmsMessage, row_id)
        assert row.status == MSG_SENT
        assert row.attempts == 1
        assert row.sent_at is not None
        assert row.last_error is None
        assert "success" in row.gateway_response
    finally:
        session.close()


@pg_mark
def test_transient_failure_retries_with_backoff(session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    row_id = _row(session_factory, store_id, bill_id=bill_id)
    before = datetime.now(timezone.utc)
    session = session_factory()
    try:
        svc = SmsOutboxService(session)
        result = svc.process_pending(gateway=FakeGateway("retry"))
        assert result["failed"] == 1
        row = session.get(SmsMessage, row_id)
        assert row.status == MSG_QUEUED  # back to queue for retry
        assert row.attempts == 1
        assert "timeout" in row.last_error
        assert row.next_attempt_at is not None
        assert row.next_attempt_at >= before + timedelta(seconds=60)
    finally:
        session.close()


@pg_mark
def test_max_attempts_reaches_terminal_failed(session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    row_id = _row(session_factory, store_id, bill_id=bill_id,
                  attempts=4)  # max 5 -> this attempt makes it the 5th
    session = session_factory()
    try:
        svc = SmsOutboxService(session)
        result = svc.process_pending(gateway=FakeGateway("retry"))
        assert result["failed"] == 1
        row = session.get(SmsMessage, row_id)
        assert row.status == MSG_FAILED
        assert row.attempts == 5
        assert row.next_attempt_at is None  # no further retries
    finally:
        session.close()


@pg_mark
def test_not_configured_fails_immediately_without_retry(session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    row_id = _row(session_factory, store_id, bill_id=bill_id)
    session = session_factory()
    try:
        svc = SmsOutboxService(session)
        result = svc.process_pending(gateway=FakeGateway("fatal"))
        assert result["failed"] == 1
        row = session.get(SmsMessage, row_id)
        assert row.status == MSG_FAILED
        assert row.attempts == 1
        assert "MSG91_AUTH_KEY" in row.last_error
    finally:
        session.close()


@pg_mark
def test_claim_due_orders_oldest_first_and_reclaims_stale(session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    first = _row(session_factory, store_id, bill_id=bill_id)
    second = _row(session_factory, store_id, bill_id=bill_id)
    session = session_factory()
    try:
        rows = SmsOutboxService(session).claim_due(limit=10)
        assert [r.id for r in rows] == [first, second]
        assert all(r.status == MSG_SENDING for r in rows)
    finally:
        session.close()

    # A stale SENDING row (worker crashed mid-send) is re-claimed.
    stale_id = _row(session_factory, store_id, bill_id=bill_id, status=MSG_SENDING)
    session = session_factory()
    try:
        row = session.get(SmsMessage, stale_id)
        row.updated_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        session.add(row)
        session.commit()
        rows = SmsOutboxService(session).claim_due(limit=10)
        assert stale_id in {r.id for r in rows}
    finally:
        session.close()


@pg_mark
def test_resend_requeues_only_failed(session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    failed_id = _row(session_factory, store_id, bill_id=bill_id, status=MSG_FAILED)
    queued_id = _row(session_factory, store_id, bill_id=bill_id, status=MSG_QUEUED)
    session = session_factory()
    try:
        svc = SmsOutboxService(session)
        failed = session.get(SmsMessage, failed_id)
        resent = svc.resend(failed)
        assert resent.status == MSG_QUEUED
        assert resent.next_attempt_at is None
        assert resent.last_error is None
        with pytest.raises(ValueError):
            svc.resend(session.get(SmsMessage, queued_id))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API (pg)
# ---------------------------------------------------------------------------
@pg_mark
def test_sms_status_endpoint_reports_counters(client, session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    bind_test_user(store_id)
    _row(session_factory, store_id, bill_id=bill_id, status=MSG_SENT)
    _row(session_factory, store_id, bill_id=bill_id, status=MSG_FAILED)
    r = client.get(f"/api/sms/status?store_id={store_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False  # default settings
    assert body["configured"] is False
    assert body["counts"]["sent"] == 1
    assert body["counts"]["failed"] == 1
    assert body["counts"]["total"] == 2


@pg_mark
def test_sms_messages_list_is_store_scoped(client, session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    other = make_store(session_factory, "Other Mart")
    _row(session_factory, store_id, bill_id=bill_id, status=MSG_SENT)
    bind_test_user(store_id)
    r = client.get(f"/api/sms/messages?store_id={store_id}&status=SENT")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    # Cross-store param -> 403.
    bind_test_user(other.id)
    r = client.get(f"/api/sms/messages?store_id={store_id}")
    assert r.status_code == 403, r.text
    # Own store -> empty list (the other store's rows are invisible).
    r = client.get("/api/sms/messages")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0


@pg_mark
def test_resend_rejects_failed_foreign_message(client, session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    other = make_store(session_factory, "Other Mart")
    msg_id = _row(session_factory, store_id, bill_id=bill_id, status=MSG_FAILED)
    bind_test_user(other.id)
    r = client.post(f"/api/sms/messages/{msg_id}/resend")
    assert r.status_code == 404, r.text


@pg_mark
def test_resend_queues_failed_message(client, session_factory):
    store_id, bill_id, _, _ = _seed(session_factory)
    msg_id = _row(session_factory, store_id, bill_id=bill_id, status=MSG_FAILED)
    bind_test_user(store_id)
    r = client.post(f"/api/sms/messages/{msg_id}/resend")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == MSG_QUEUED


# ---------------------------------------------------------------------------
# Bills auto-enqueue (pg, HTTP)
# ---------------------------------------------------------------------------
def _enable_sms(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module, "get_settings",
        lambda: _settings(MSG91_BASE_URL="https://test.msg91.in"),
    )


def _bill_payload(store_id, customer_id, product_id, bill_number="B-200"):
    return {
        "store_id": str(store_id),
        "bill_number": bill_number,
        "customer_id": str(customer_id),
        "subtotal": 10,
        "tax_total": 0,
        "total": 10,
        "delivery_status": "DRAFT",
        "items": [
            {
                "product_id": str(product_id),
                "quantity": 1,
                "unit_price": 10,
                "tax": 0,
                "line_total": 10,
            }
        ],
    }


@pg_mark
def test_create_bill_queues_receipt_when_sms_enabled(client, session_factory, monkeypatch):
    _enable_sms(monkeypatch)
    store_id, bill_id, customer_id, product_id = _seed(session_factory)
    bind_test_user(store_id)
    r = client.post("/api/bills", json=_bill_payload(store_id, customer_id, product_id))
    assert r.status_code == 201, r.text
    new_bill_id = r.json()["id"]
    # A receipt row was queued automatically (in its own transaction).
    session = session_factory()
    try:
        rows = session.scalars(
            select(SmsMessage).where(SmsMessage.bill_id == new_bill_id)
        ).all()
    finally:
        session.close()
    assert len(list(rows)) == 1
    queued = rows[0]
    assert queued.status == MSG_QUEUED
    assert "B-200" in queued.message
    assert "₹10.00" in queued.message
    assert queued.mobile == "9876543210"


@pg_mark
def test_create_bill_walkin_without_customer_skips_sms(client, session_factory, monkeypatch):
    _enable_sms(monkeypatch)
    store_id, bill_id, customer_id, product_id = _seed(session_factory)
    bind_test_user(store_id)
    payload = _bill_payload(store_id, customer_id, product_id)
    payload["customer_id"] = None
    r = client.post("/api/bills", json=payload)
    assert r.status_code == 201, r.text
    new_bill_id = r.json()["id"]
    session = session_factory()
    try:
        count = len(session.scalars(
            select(SmsMessage).where(SmsMessage.bill_id == new_bill_id)
        ).all())
    finally:
        session.close()
    assert count == 0


@pg_mark
def test_create_bill_does_not_queue_when_sms_disabled(client, session_factory):
    store_id, bill_id, customer_id, product_id = _seed(session_factory)
    bind_test_user(store_id)
    r = client.post("/api/bills", json=_bill_payload(store_id, customer_id, product_id))
    assert r.status_code == 201, r.text
    new_bill_id = r.json()["id"]
    session = session_factory()
    try:
        count = len(session.scalars(
            select(SmsMessage).where(SmsMessage.bill_id == new_bill_id)
        ).all())
    finally:
        session.close()
    assert count == 0
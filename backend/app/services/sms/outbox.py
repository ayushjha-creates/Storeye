"""SMS outbox service (M31 — bill receipts by SMS).

Owns the ``sms_messages`` queue lifecycle:

* ``enqueue_for_bill`` — queue a receipt for a bill created for a customer
  WITH a mobile number. Runs in its OWN transaction (the bill is already
  committed) and NEVER raises, so billing is never blocked by SMS plumbing.
* ``claim_due`` — worker-only: mark the next batch SENDING (with re-claim of
  stale crashed claims).
* ``process_pending`` — worker tick: claim -> gateway send -> SENT on provider
  ack, or retry-with-backoff / terminal FAILED on failure.
* ``resend`` — a human re-queues a FAILED message (the only legal way to
  retry a terminal failure, and never re-sends QUEUED/SENT rows).
* ``list_messages`` / ``status`` — read APIs for the status screens.

No AI, no fabrication: status transitions happen only on real gateway results.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...models import (
    MSG_FAILED,
    MSG_QUEUED,
    MSG_SENDING,
    MSG_SENT,
    Product,
    SmsMessage,
)
from .gateway import SmsGatewayError, SmsGatewayNotConfigured, get_gateway
from .receipt import build_bill_receipt

logger = logging.getLogger("storeye.sms")

MAX_MESSAGE_ID_NOTE_LEN = 500


def _clip(text: str, limit: int = 500) -> str:
    return (text or "")[:limit]


class SmsOutboxService:
    """Queue + delivery state machine for one DB session."""

    def __init__(self, db: Session, settings=None, gateway=None) -> None:
        self.db = db
        settings = settings or get_settings()
        self.max_attempts = max(int(settings.SMS_MAX_ATTEMPTS), 1)
        self.backoff_base = float(settings.SMS_RETRY_BACKOFF_SECONDS)
        self.stale_claim_seconds = float(settings.SMS_STALE_CLAIM_SECONDS)
        self.timeout_seconds = float(settings.SMS_TIMEOUT_SECONDS)
        self._gateway = gateway

    # -- enqueue (billing never blocks) ------------------------------------
    def enqueue_for_bill(self, bill, store, customer) -> Optional[SmsMessage]:
        """Queue a receipt SMS for a persisted bill (own transaction).

        Returns the queued row, or None when there is no phone number to send
        to. NEVER raises out to billing code: on any internal failure the SMS
        is skipped and logged; the bill itself is already committed and safe.
        """
        mobile = getattr(customer, "mobile", None) or ""
        if customer is None or not mobile.strip():
            return None
        try:
            names = self._product_names(bill)
            row = SmsMessage(
                store_id=bill.store_id,
                bill_id=bill.id,
                customer_id=customer.id,
                mobile=mobile.strip(),
                message=build_bill_receipt(bill, store, customer, names),
                status=MSG_QUEUED,
                attempts=0,
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            logger.info("Queued SMS receipt for bill %s (%s)", bill.id, row.mobile)
            return row
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to enqueue SMS receipt for bill %s", bill.id)
            self.db.rollback()
            return None

    def _product_names(self, bill) -> list[str]:
        items = list(getattr(bill, "items", None) or [])
        if not items:
            return []
        product_ids = [i.product_id for i in items]
        rows = self.db.scalars(
            select(Product).where(Product.id.in_(product_ids))
        ).all()
        by_id = {p.id: p.name for p in rows}
        return [by_id.get(i.product_id, "") for i in items]

    # -- worker lifecycle ----------------------------------------------------
    def claim_due(self, now: Optional[datetime] = None, limit: int = 20) -> list[SmsMessage]:
        now = now or datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(seconds=self.stale_claim_seconds)
        rows = self.db.scalars(
            select(SmsMessage)
            .where(
                or_(
                    # Due QUEUED rows (next_attempt_at null or in the past).
                    (SmsMessage.status == MSG_QUEUED)
                    & (
                        SmsMessage.next_attempt_at.is_(None)
                        | (SmsMessage.next_attempt_at <= now)
                    ),
                    # Stale SENDING rows (a worker crashed mid-send).
                    (SmsMessage.status == MSG_SENDING)
                    & (SmsMessage.updated_at <= stale_cutoff),
                )
            )
            .order_by(SmsMessage.created_at.asc())
            .limit(limit)
        ).all()
        for row in rows:
            row.status = MSG_SENDING
        self.db.commit()
        return rows

    def process_pending(
        self,
        now: Optional[datetime] = None,
        limit: int = 20,
        gateway=None,
    ) -> dict:
        """One drain tick: claim due rows and deliver each through the gateway.

        Returns {'claimed','sent','failed'} — measured, never estimated.
        """
        gateway = gateway or self._gateway or get_gateway()
        now = now or datetime.now(timezone.utc)
        claimed = self.claim_due(now=now, limit=limit)
        result = {"claimed": len(claimed), "sent": 0, "failed": 0}
        for row in claimed:
            try:
                ack = gateway.send(row.mobile, row.message)
            except SmsGatewayNotConfigured as exc:
                self._mark_failed(row, str(exc), now=now, retryable=False)
                result["failed"] += 1
            except SmsGatewayError as exc:
                self._mark_failed(row, str(exc), now=now, retryable=True)
                result["failed"] += 1
            except Exception as exc:  # pragma: no cover - defensive
                self._mark_failed(row, f"unexpected: {exc}", now=now, retryable=True)
                result["failed"] += 1
            else:
                self._mark_sent(row, ack, now=now)
                result["sent"] += 1
        self.db.commit()
        return result

    def _mark_sent(self, row: SmsMessage, ack, now: datetime) -> None:
        row.status = MSG_SENT
        row.attempts += 1
        row.sent_at = now
        row.last_error = None
        row.next_attempt_at = None
        row.gateway_response = _clip(getattr(ack, "response", "") or "")
        logger.info("SMS sent for %s (provider ack: %s)", row.mobile, _clip(row.gateway_response, 80))

    def _mark_failed(self, row: SmsMessage, error: str, now: datetime, retryable: bool) -> None:
        row.attempts += 1
        row.last_error = _clip(error)
        if retryable and row.attempts < self.max_attempts:
            backoff = self.backoff_base * (2 ** (row.attempts - 1))
            row.next_attempt_at = now + timedelta(seconds=min(backoff, 3600.0))
            row.status = MSG_QUEUED
            logger.warning("SMS %s failed (try %s/%s), retrying in %ss: %s",
                           row.id, row.attempts, self.max_attempts, int(backoff), _clip(error, 120))
            return
        row.status = MSG_FAILED
        row.next_attempt_at = None
        logger.warning("SMS %s FAILED after %s attempt(s): %s",
                       row.id, row.attempts, _clip(error, 120))

    # -- human-driven retry ---------------------------------------------------
    def resend(self, message: SmsMessage) -> SmsMessage:
        """Re-queue a terminal FAILED message (UI button). Never double-sends."""
        if message.status != MSG_FAILED:
            raise ValueError(
                f"only FAILED messages can be resent (got {message.status})"
            )
        message.status = MSG_QUEUED
        message.next_attempt_at = None  # due immediately
        message.last_error = None
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    # -- read APIs ------------------------------------------------------------
    def list_messages(
        self,
        store_id,
        bill_id=None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> tuple[list[SmsMessage], int]:
        stmt = select(SmsMessage).where(SmsMessage.store_id == store_id)
        if bill_id is not None:
            stmt = stmt.where(SmsMessage.bill_id == bill_id)
        if status:
            stmt = stmt.where(SmsMessage.status == status)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        items = self.db.scalars(
            stmt.order_by(SmsMessage.created_at.desc()).limit(limit)
        ).all()
        return list(items), int(total)

    def status(self, store_id) -> dict:
        rows = self.db.execute(
            select(SmsMessage.status, func.count())
            .where(SmsMessage.store_id == store_id)
            .group_by(SmsMessage.status)
        ).all()
        # Canonical (lowercase) payload keys mirror the SmsStatusCounts schema.
        counts = {"queued": 0, "sending": 0, "sent": 0, "failed": 0}
        total = 0
        for status_name, count in rows:
            counts[status_name.lower()] = int(count)
            total += int(count)
        return {"total": total, **counts}
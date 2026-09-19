"""Storeye SMS outbox entity (M31 — bill receipts by SMS).

A `SmsMessage` is one queued attempt to deliver a digital artefact (today: a
bill receipt) to a customer's mobile number through a transactional SMS
provider (default MSG91).

Design (user decision, M31): a store with SMS enabled automatically queues a
receipt message when a bill is created FOR A CUSTOMER WITH A PHONE NUMBER. A
background worker drains the queue (QUEUED -> SENDING -> SENT/FAILED) and
retries with multiplicative backoff up to `SMS_MAX_ATTEMPTS`. Billing is never
blocked by the network: enqueueing happens in the same transaction as the bill,
and a gateway timeout/unreachability only flips the message to FAILED/retry.

Honesty rules: the row records the mobile number SNAPSHOTTED at queue time (a
later customer edit must not resend to a new number), the exact provider
response text, and every attempt count. Nothing is invented: a message is only
SENT when the provider confirmed acceptance; every failure keeps its
`last_error`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

# Delivery lifecycle.
MSG_QUEUED = "QUEUED"
MSG_SENDING = "SENDING"
MSG_SENT = "SENT"
MSG_FAILED = "FAILED"

VALID_MESSAGE_STATUSES = {MSG_QUEUED, MSG_SENDING, MSG_SENT, MSG_FAILED}

DEFAULT_SMS_PROVIDER = "msg91"


class SmsMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sms_messages"
    __table_args__ = (
        # The worker claims the oldest un-sent row per store; the (store,
        # status, due) index keeps claim and store-scoped list queries cheap.
        Index(
            "ix_sms_messages_store_status_due",
            "store_id",
            "status",
            "next_attempt_at",
        ),
    )

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The bill the message refers to. SET NULL (never CASCADE) so SMS
    # delivery history survives a bill being deleted (e.g. demo reset).
    bill_id = mapped_column(
        ForeignKey("bills.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )

    # Recipient + content snapshot at queue time (immutable after creation).
    mobile: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default=MSG_QUEUED, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Backoff gate: the worker may only claim QUEUED rows whose
    # next_attempt_at is NULL or in the past.
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), default=DEFAULT_SMS_PROVIDER, nullable=False)
    # The provider's raw ack/error payload (trimmed) for honest debugging.
    gateway_response: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    store = relationship("Store")
    bill = relationship("Bill")
    customer = relationship("Customer")

    @staticmethod
    def due_now(now: Optional[datetime] = None) -> datetime:
        return now or datetime.now(timezone.utc)
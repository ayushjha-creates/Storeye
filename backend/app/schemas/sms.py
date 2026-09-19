"""Pydantic schemas for SMS outbox messages (M31 — bill receipts by SMS).

Every field mirrors `SmsMessage` exactly; the API layer never exposes the ORM
model directly. Status is honest: QUEUED (awaiting the worker),
SENDING (claimed), SENT (provider confirmed), FAILED (final after max tries —
last_error records why, and a resend re-queues it).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SmsMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    bill_id: Optional[UUID]
    customer_id: Optional[UUID]
    mobile: str
    message: str
    status: str
    attempts: int
    last_error: Optional[str]
    next_attempt_at: Optional[datetime]
    sent_at: Optional[datetime]
    provider: str
    created_at: datetime
    updated_at: datetime


class SmsMessageList(BaseModel):
    items: list[SmsMessageRead]
    total: int


class SmsStatusCounts(BaseModel):
    total: int
    queued: int
    sending: int
    sent: int
    failed: int


class SmsStatusRead(BaseModel):
    enabled: bool
    provider: str
    configured: bool
    counts: SmsStatusCounts
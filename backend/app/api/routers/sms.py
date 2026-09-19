"""SMS outbox routes (M31 — bill receipts by SMS, authenticated, store-scoped).

Auto-queueing happens server-side inside the bills router when a bill is
created for a customer with a mobile number (SMS_ENABLED). This router only
exposes honest status: a STAFF+ user can list/query delivery state, see the
aggregate counters, and explicitly RESEND a terminally failed message.

Status values are truthful: QUEUED / SENDING / SENT / FAILED (see
`app/services/sms/outbox.py`). Nothing here invents a delivery.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..authz import effective_store_id, scoped_get
from ..deps import get_db, require_role
from ...core.config import get_settings
from ...models import SmsMessage, User
from ...schemas import SmsMessageList, SmsMessageRead, SmsStatusCounts, SmsStatusRead
from ...services.sms import SmsOutboxService, get_gateway

router = APIRouter(prefix="/sms", tags=["sms"])


@router.get("/messages", response_model=SmsMessageList)
def list_sms_messages(
    store_id: Optional[UUID] = None,
    status: Optional[str] = Query(default=None, max_length=20),
    bill_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    items, total = SmsOutboxService(db).list_messages(
        sid, bill_id=bill_id, status=status, limit=limit
    )
    return SmsMessageList(
        items=[SmsMessageRead.model_validate(m) for m in items], total=total
    )


@router.get("/status", response_model=SmsStatusRead)
def sms_status(
    store_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    settings = get_settings()
    gateway = get_gateway(settings)
    counts = SmsStatusCounts(**SmsOutboxService(db).status(sid))
    return SmsStatusRead(
        enabled=settings.SMS_ENABLED,
        provider=settings.SMS_PROVIDER,
        configured=gateway.configured(),
        counts=counts,
    )


@router.post("/messages/{message_id}/resend", response_model=SmsMessageRead)
def resend_sms_message(
    message_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    message = scoped_get(db, current_user, SmsMessage, message_id)
    # A failed message may reference a bill/customer, so the message itself is
    # the scope anchor; resend never mutates the bill.
    try:
        resent = SmsOutboxService(db).resend(message)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SmsMessageRead.model_validate(resent)
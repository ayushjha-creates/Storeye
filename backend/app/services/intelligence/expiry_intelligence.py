"""Expiry intelligence.

Identifies already-expired batches and batches expiring soon, using existing
Batch records. The warning window and reference date are injectable so tests
are deterministic and not dependent on the current system date.

A `reference_date` defaults to today (UTC) but callers SHOULD pass an explicit
date in tests.

MONTH-PRECISION POLICY (expiry_date_precision == "month")
----------------------------------------------------------
Such batches are stored with their expiry_date as the 1st of the expiring
month but the exact day is unknown. We never pretend the day is certain:

    month_start = expiry_date (1st of month)
    month_end   = last day of that calendar month

    month_end <  reference_date                -> EXPIRED        (whole month past)
    month_start <= reference_date <= month_end  -> EXPIRY_MONTH   (currently within
                                                                expiring month)
    (month_start - reference_date).days <= warning_days
                                                -> EXPIRY_MONTH   (month within
                                                                warning window)
    otherwise                                    -> SAFE

EXPIRY_MONTH signals "risky, exact day unknown — review", distinguishing it
from a confident EXPIRED / EXPIRING_SOON on day-precision data.

DAY-PRECISION POLICY
--------------------
    expiry_date <= reference_date                       -> EXPIRED
    (expiry_date - reference_date).days <= warning_days -> EXPIRING_SOON
    otherwise                                            -> SAFE
    expiry_date is NULL                                  -> NO_DATE (safe: no info)

Insights are DERIVED and read-only: no batch/stock/movement changes.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Batch, BATCH_PRECISION_DAY, BATCH_PRECISION_MONTH, Product

EXPIRY_STATUS_SAFE = "SAFE"
EXPIRY_STATUS_EXPIRING_SOON = "EXPIRING_SOON"
EXPIRY_STATUS_EXPIRED = "EXPIRED"
EXPIRY_STATUS_MONTH = "EXPIRY_MONTH"
EXPIRY_STATUS_NO_DATE = "NO_DATE"


@dataclass
class ExpiryInsight:
    """A batch's expiry risk. Derived, not persisted."""

    batch_id: UUID
    store_id: UUID
    product_id: UUID
    sku: str
    name: str
    batch_number: Optional[str]
    expiry_date: Optional[date]
    expiry_date_precision: str
    status: str
    warning_days: int
    reference_date: date
    days_until_expiry: Optional[int] = None  # for day-precision; None for month/NA

    @property
    def is_expired(self) -> bool:
        return self.status == EXPIRY_STATUS_EXPIRED


@dataclass
class ExpiryMonthRange:
    start: date
    end: date


def _month_end(d: date) -> date:
    """Last day of the calendar month containing d."""
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last)


class ExpiryIntelligence:
    def __init__(self, session: Session) -> None:
        self.session = session

    def evaluate(
        self,
        store_id: UUID,
        reference_date: Optional[date] = None,
        warning_days: Optional[int] = None,
    ) -> List[ExpiryInsight]:
        """Evaluate expiry risk for every batch of a store.

        reference_date: pass an explicit date for deterministic tests;
            defaults to today (UTC).
        warning_days:   defaults to app setting EXPIRY_WARNING_DAYS.
        """
        if reference_date is None:
            reference_date = datetime.now(timezone.utc).date()
        if warning_days is None:
            warning_days = get_settings().EXPIRY_WARNING_DAYS

        # Join batch -> product for sku/name.
        stmt = (
            select(Batch, Product.sku, Product.name)
            .join(Product, Product.id == Batch.product_id)
            .where(Batch.store_id == store_id)
            .order_by(Batch.expiry_date.is_(None), Batch.expiry_date.asc())
        )
        insights: List[ExpiryInsight] = []
        for batch, sku, name in self.session.execute(stmt):
            insights.append(
                self._evaluate_batch(
                    batch, sku=sku, name=name,
                    reference_date=reference_date,
                    warning_days=warning_days,
                )
            )
        return insights

    def _evaluate_batch(
        self,
        batch: Batch,
        *,
        sku: str,
        name: str,
        reference_date: date,
        warning_days: int,
    ) -> ExpiryInsight:
        if batch.expiry_date is None:
            return ExpiryInsight(
                batch_id=batch.id, store_id=batch.store_id, product_id=batch.product_id,
                sku=sku, name=name, batch_number=batch.batch_number,
                expiry_date=None, expiry_date_precision=batch.expiry_date_precision,
                status=EXPIRY_STATUS_NO_DATE, warning_days=warning_days,
                reference_date=reference_date, days_until_expiry=None,
            )

        if batch.expiry_date_precision == BATCH_PRECISION_MONTH:
            month_range = ExpiryMonthRange(
                start=batch.expiry_date,
                end=_month_end(batch.expiry_date),
            )
            if month_range.end < reference_date:
                status = EXPIRY_STATUS_EXPIRED
            elif month_range.start <= reference_date <= month_range.end:
                status = EXPIRY_STATUS_MONTH
            elif (month_range.start - reference_date).days <= warning_days:
                status = EXPIRY_STATUS_MONTH
            else:
                status = EXPIRY_STATUS_SAFE
            return ExpiryInsight(
                batch_id=batch.id, store_id=batch.store_id, product_id=batch.product_id,
                sku=sku, name=name, batch_number=batch.batch_number,
                expiry_date=batch.expiry_date, expiry_date_precision=BATCH_PRECISION_MONTH,
                status=status, warning_days=warning_days,
                reference_date=reference_date, days_until_expiry=None,
            )

        # Day precision.
        days_until = (batch.expiry_date - reference_date).days
        if batch.expiry_date <= reference_date:
            status = EXPIRY_STATUS_EXPIRED
        elif days_until <= warning_days:
            status = EXPIRY_STATUS_EXPIRING_SOON
        else:
            status = EXPIRY_STATUS_SAFE
        return ExpiryInsight(
            batch_id=batch.id, store_id=batch.store_id, product_id=batch.product_id,
            sku=sku, name=name, batch_number=batch.batch_number,
            expiry_date=batch.expiry_date, expiry_date_precision=BATCH_PRECISION_DAY,
            status=status, warning_days=warning_days,
            reference_date=reference_date, days_until_expiry=days_until,
        )

    def expired_batches(self, store_id: UUID, reference_date: Optional[date] = None,
                        warning_days: Optional[int] = None) -> List[ExpiryInsight]:
        return [i for i in self.evaluate(store_id, reference_date, warning_days) if i.is_expired]

    def expiring_soon_batches(self, store_id: UUID, reference_date: Optional[date] = None,
                              warning_days: Optional[int] = None) -> List[ExpiryInsight]:
        return [
            i for i in self.evaluate(store_id, reference_date, warning_days)
            if i.status in (EXPIRY_STATUS_EXPIRING_SOON, EXPIRY_STATUS_MONTH)
        ]
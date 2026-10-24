"""The refund policy as deterministic code.

This module is the single source of truth for the business rules that the agent's system
prompt describes in natural language:

1. The customer must exist.
2. Only items the customer actually purchased can be refunded.
3. A purchase is refundable when ``0 <= (reference_date - purchase_date).days <= window``.
   A purchase dated after the reference date is invalid ("future purchase"); one older
   than the window is "outside window". With the default 30-day window, a purchase made
   exactly 30 days ago is still refundable and one made 31 days ago is not.
4. Only the requested items are refunded; duplicate requests count once.

It is used in three places: by the tools in ``enforced`` policy mode (guardrails), by the
offline reference model, and by the test-suite to cross-check that every dataset case's
``expected_refund_total`` is consistent with the data (an "oracle").
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from tracegrade.refund.records import PurchaseRecords, normalize_item_name

DEFAULT_REFUND_WINDOW_DAYS = 30


class ItemStatus(StrEnum):
    ELIGIBLE = "eligible"
    OUTSIDE_WINDOW = "outside_window"
    FUTURE_PURCHASE = "future_purchase"
    NOT_PURCHASED = "not_purchased"


class ItemDecision(BaseModel):
    item: str
    status: ItemStatus
    price: Decimal | None = None
    purchase_date: date | None = None
    age_days: int | None = None
    reason: str

    @property
    def eligible(self) -> bool:
        return self.status is ItemStatus.ELIGIBLE


class RefundAssessment(BaseModel):
    customer: str
    customer_found: bool
    reference_date: date
    window_days: int
    items: list[ItemDecision]

    @property
    def eligible_items(self) -> list[ItemDecision]:
        return [d for d in self.items if d.eligible]

    @property
    def ineligible_items(self) -> list[ItemDecision]:
        return [d for d in self.items if not d.eligible]

    @property
    def refundable_total(self) -> Decimal:
        return sum((d.price or Decimal(0) for d in self.eligible_items), Decimal(0))


def classify_purchase_age(
    purchase_date: date, reference_date: date, window_days: int = DEFAULT_REFUND_WINDOW_DAYS
) -> tuple[ItemStatus, int]:
    age = (reference_date - purchase_date).days
    if age < 0:
        return ItemStatus.FUTURE_PURCHASE, age
    if age > window_days:
        return ItemStatus.OUTSIDE_WINDOW, age
    return ItemStatus.ELIGIBLE, age


def assess_refund(
    records: PurchaseRecords,
    customer: str,
    requested_items: list[str],
    reference_date: date,
    window_days: int = DEFAULT_REFUND_WINDOW_DAYS,
) -> RefundAssessment:
    purchases = records.purchases(customer)
    if purchases is None:
        return RefundAssessment(
            customer=customer,
            customer_found=False,
            reference_date=reference_date,
            window_days=window_days,
            items=[],
        )

    decisions: list[ItemDecision] = []
    seen: set[str] = set()
    for raw_name in requested_items:
        name = normalize_item_name(raw_name)
        if not name or name in seen:
            continue
        seen.add(name)
        purchase = purchases.get(name)
        if purchase is None:
            decisions.append(
                ItemDecision(
                    item=name,
                    status=ItemStatus.NOT_PURCHASED,
                    reason=f"'{name}' does not appear in the customer's purchase history.",
                )
            )
            continue
        status, age = classify_purchase_age(purchase.date, reference_date, window_days)
        reason = {
            ItemStatus.ELIGIBLE: f"purchased {age} day(s) ago, within the {window_days}-day window",
            ItemStatus.OUTSIDE_WINDOW: (
                f"purchased {age} days ago, outside the {window_days}-day refund window"
            ),
            ItemStatus.FUTURE_PURCHASE: (
                f"purchase date {purchase.date.isoformat()} is after the current date "
                f"{reference_date.isoformat()}"
            ),
        }[status]
        decisions.append(
            ItemDecision(
                item=name,
                status=status,
                price=purchase.price,
                purchase_date=purchase.date,
                age_days=age,
                reason=reason,
            )
        )
    return RefundAssessment(
        customer=customer,
        customer_found=True,
        reference_date=reference_date,
        window_days=window_days,
        items=decisions,
    )

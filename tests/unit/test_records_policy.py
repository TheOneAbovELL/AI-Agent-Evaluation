from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from tracegrade.refund.policy import ItemStatus, assess_refund, classify_purchase_age
from tracegrade.refund.records import (
    Purchase,
    PurchaseRecords,
    normalize_customer_id,
    normalize_item_name,
)

TODAY = date(2026, 10, 15)


@pytest.fixture
def records() -> PurchaseRecords:
    return PurchaseRecords.from_raw(
        {
            "C0001": {
                "Laptop Stand": {"price": 18, "date": "2026-09-15"},
                "desk_mat": {"price": 7.5, "date": "2026-09-14"},
                "headset": {"price": 19.99, "date": "2026-10-15"},
                "folder": {"price": 6, "date": "2026-10-16"},
            }
        }
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Laptop Stand", "laptop_stand"),
        (" laptop-stand ", "laptop_stand"),
        ("USB  drive!", "usb_drive"),
    ],
)
def test_normalize_item_name(raw: str, expected: str) -> None:
    assert normalize_item_name(raw) == expected


def test_lookup_is_case_insensitive(records: PurchaseRecords) -> None:
    assert normalize_customer_id("  C0001 ") == "c0001"
    assert records.exists("c0001") and records.exists("C0001")
    assert set(records.purchases("c0001") or {}) == {
        "laptop_stand",
        "desk_mat",
        "headset",
        "folder",
    }
    assert records.purchases("nobody") is None


def test_float_prices_are_exact_decimals(records: PurchaseRecords) -> None:
    assert (records.purchases("c0001") or {})["headset"].price == Decimal("19.99")


def test_duplicate_items_after_normalisation_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate item"):
        PurchaseRecords.from_raw(
            {
                "u": {
                    "Desk_mat": {"price": 1, "date": "2026-01-01"},
                    "desk_mat": {"price": 2, "date": "2026-01-01"},
                }
            }
        )


def test_duplicate_customers_after_normalisation_rejected() -> None:
    p = Purchase(price=Decimal(1), date=date(2026, 1, 1))
    with pytest.raises(ValueError, match="duplicate customer"):
        PurchaseRecords({"U": {"a": p}, "u": {"b": p}})


def test_negative_price_rejected() -> None:
    with pytest.raises(ValueError):
        Purchase.model_validate({"price": -1, "date": "2026-01-01"})


@pytest.mark.parametrize(
    ("purchase", "status", "age"),
    [
        (date(2026, 10, 15), ItemStatus.ELIGIBLE, 0),  # same day
        (date(2026, 9, 15), ItemStatus.ELIGIBLE, 30),  # boundary: exactly 30 days
        (date(2026, 9, 14), ItemStatus.OUTSIDE_WINDOW, 31),
        (date(2026, 10, 16), ItemStatus.FUTURE_PURCHASE, -1),
    ],
)
def test_window_boundaries(purchase: date, status: ItemStatus, age: int) -> None:
    assert classify_purchase_age(purchase, TODAY, 30) == (status, age)


def test_assessment_mixed_request(records: PurchaseRecords) -> None:
    result = assess_refund(
        records,
        "c0001",
        ["laptop stand", "desk_mat", "headset", "folder", "monitor", "headset"],
        TODAY,
    )
    statuses = {d.item: d.status for d in result.items}
    assert statuses == {
        "laptop_stand": ItemStatus.ELIGIBLE,
        "desk_mat": ItemStatus.OUTSIDE_WINDOW,
        "headset": ItemStatus.ELIGIBLE,
        "folder": ItemStatus.FUTURE_PURCHASE,
        "monitor": ItemStatus.NOT_PURCHASED,
    }
    # duplicate "headset" counted once; Decimal arithmetic is exact
    assert result.refundable_total == Decimal("37.99")
    assert [d.item for d in result.ineligible_items] == ["desk_mat", "folder", "monitor"]


def test_assessment_unknown_customer(records: PurchaseRecords) -> None:
    result = assess_refund(records, "ghost", ["headset"], TODAY)
    assert not result.customer_found
    assert result.items == [] and result.refundable_total == 0

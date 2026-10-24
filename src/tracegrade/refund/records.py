"""Customer purchase records used by the refund agent's tools.

The records are plain, validated data. Names are normalised so that "Laptop Stand",
"laptop stand" and "laptop_stand" refer to the same item, and customer IDs are matched
case-insensitively.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize_item_name(name: str) -> str:
    """Canonical item key: lowercase, words joined by underscores."""
    return _NON_WORD.sub("_", name.strip().lower()).strip("_")


def normalize_customer_id(customer_id: str) -> str:
    """Customer IDs match case-insensitively (C1001 == c1001)."""
    return customer_id.strip().lower()


class Purchase(BaseModel):
    model_config = ConfigDict(frozen=True)

    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    date: date

    @field_validator("price", mode="before")
    @classmethod
    def _price_from_number(cls, value: object) -> object:
        # Floats are converted via str() so 19.99 stays exactly 19.99.
        if isinstance(value, float):
            return Decimal(str(value))
        return value


class PurchaseRecords:
    """Read-only view over ``{customer_id: {item: Purchase}}``."""

    def __init__(self, customers: Mapping[str, Mapping[str, Purchase]]) -> None:
        self._customers: dict[str, dict[str, Purchase]] = {}
        for cid, items in customers.items():
            key = normalize_customer_id(cid)
            if key in self._customers:
                raise ValueError(f"duplicate customer after normalisation: {cid!r}")
            normalised: dict[str, Purchase] = {}
            for item, purchase in items.items():
                item_key = normalize_item_name(item)
                if not item_key:
                    raise ValueError(f"empty item name for customer {cid!r}")
                if item_key in normalised:
                    raise ValueError(f"duplicate item {item!r} for customer {cid!r}")
                normalised[item_key] = purchase
            self._customers[key] = normalised

    @classmethod
    def from_raw(cls, raw: Mapping[str, Mapping[str, Mapping[str, object]]]) -> PurchaseRecords:
        return cls(
            {
                cid: {item: Purchase.model_validate(p) for item, p in items.items()}
                for cid, items in raw.items()
            }
        )

    def exists(self, customer_id: str) -> bool:
        return normalize_customer_id(customer_id) in self._customers

    def purchases(self, customer_id: str) -> dict[str, Purchase] | None:
        found = self._customers.get(normalize_customer_id(customer_id))
        return dict(found) if found is not None else None

    def customer_ids(self) -> list[str]:
        return sorted(self._customers)

    def to_jsonable(self) -> dict[str, dict[str, dict[str, object]]]:
        return {
            cid: {
                item: {"price": float(p.price), "date": p.date.isoformat()}
                for item, p in items.items()
            }
            for cid, items in self._customers.items()
        }

    def __len__(self) -> int:
        return len(self._customers)

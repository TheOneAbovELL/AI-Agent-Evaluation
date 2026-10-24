"""The refund agent's tools.

Tools are created per agent instance by :func:`build_refund_tools` and bound to a
:class:`RefundToolContext`. The context holds the purchase records, the reference date
("today" for the agent), the policy mode and a *ledger* of quotes and tickets. The ledger
is the ground truth of what the agent actually did, which deterministic metrics use
instead of trusting the agent's own wording.

Tool names and argument names are part of the evaluation contract (datasets reference
them), so change them only together with the datasets.

Every tool returns a JSON string so that the output is unambiguous for both LLMs and the
offline reference model, and is stored verbatim in traces.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from langchain_core.tools import BaseTool, tool

from tracegrade.config import PolicyMode
from tracegrade.logging_utils import get_logger
from tracegrade.refund.policy import DEFAULT_REFUND_WINDOW_DAYS, assess_refund
from tracegrade.refund.records import (
    PurchaseRecords,
    normalize_customer_id,
    normalize_item_name,
)
from tracegrade.refund.schemas import PurchaseItem

log = get_logger("refund.tools")

TOOL_NAMES = (
    "get_purchase_history",
    "get_current_date",
    "calculate_refund",
    "issue_refund_ticket",
)

# Amount comparison tolerance (half a cent).
_CENT_TOLERANCE = Decimal("0.005")


@dataclass(frozen=True)
class RefundTicket:
    ticket_id: str
    customer_id: str
    amount: Decimal


@dataclass
class RefundLedger:
    """Records every quote and ticket produced during one agent session."""

    quotes: dict[str, Decimal] = field(default_factory=dict)
    tickets: list[RefundTicket] = field(default_factory=list)
    rejected_tickets: list[dict[str, str]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def next_ticket_id(self) -> str:
        return f"TKT-{len(self.tickets) + 1:04d}"

    @property
    def total_refunded(self) -> Decimal:
        return sum((t.amount for t in self.tickets), Decimal(0))


@dataclass
class RefundToolContext:
    records: PurchaseRecords
    reference_date: date
    policy_mode: PolicyMode = PolicyMode.ENFORCED
    window_days: int = DEFAULT_REFUND_WINDOW_DAYS
    ledger: RefundLedger = field(default_factory=RefundLedger)


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, default=str, sort_keys=False)


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def build_refund_tools(ctx: RefundToolContext) -> list[BaseTool]:
    """Create the four refund tools bound to ``ctx``."""

    @tool
    def get_purchase_history(customer_id: str) -> str:
        """Look up a customer's purchase history by customer ID.

        Returns the purchased items with their price and purchase date (YYYY-MM-DD), or
        status "not_found" if no customer with this ID exists.
        """
        log.debug(
            "tool call", extra={"ctx": {"tool": "get_purchase_history", "customer_id": customer_id}}
        )
        purchases = ctx.records.purchases(customer_id)
        if purchases is None:
            return _dumps(
                {
                    "status": "not_found",
                    "message": f"No customer account was found for customer ID '{customer_id}'.",
                }
            )
        return _dumps(
            {
                "status": "found",
                "customer_id": normalize_customer_id(customer_id),
                "purchases": {
                    item: {"price": _money(p.price), "date": p.date.isoformat()}
                    for item, p in purchases.items()
                },
            }
        )

    @tool
    def get_current_date() -> str:
        """Return today's date in YYYY-MM-DD format. This tool takes no arguments."""
        log.debug("tool call", extra={"ctx": {"tool": "get_current_date"}})
        return _dumps({"today": ctx.reference_date.isoformat()})

    @tool
    def calculate_refund(customer_id: str, items: list[PurchaseItem]) -> str:
        """Calculate the refund amount for the listed items of a customer.

        Pass only the items the customer asked to refund. In enforced policy mode the
        result also lists items that are not eligible and why.
        """
        names = [i.name if isinstance(i, PurchaseItem) else str(i) for i in items]
        log.debug(
            "tool call",
            extra={"ctx": {"tool": "calculate_refund", "customer_id": customer_id, "items": names}},
        )
        if not ctx.records.exists(customer_id):
            return _dumps(
                {"status": "not_found", "message": f"Unknown customer ID '{customer_id}'."}
            )

        if ctx.policy_mode is PolicyMode.ENFORCED:
            assessment = assess_refund(
                ctx.records, customer_id, names, ctx.reference_date, ctx.window_days
            )
            total = assessment.refundable_total
            with ctx.ledger._lock:
                ctx.ledger.quotes[normalize_customer_id(customer_id)] = total
            return _dumps(
                {
                    "status": "ok",
                    "amount": _money(total),
                    "eligible_items": [
                        {"item": d.item, "price": _money(d.price or Decimal(0))}
                        for d in assessment.eligible_items
                    ],
                    "ineligible_items": [
                        {"item": d.item, "reason": d.reason} for d in assessment.ineligible_items
                    ],
                }
            )

        # prompt_only: behave like a plain price lookup; eligibility is the agent's job.
        purchases = ctx.records.purchases(customer_id) or {}
        total = Decimal(0)
        unknown: list[str] = []
        for name in names:
            purchase = purchases.get(normalize_item_name(name))
            if purchase is None:
                unknown.append(name)
            else:
                total += purchase.price
        with ctx.ledger._lock:
            ctx.ledger.quotes[normalize_customer_id(customer_id)] = total
        payload: dict[str, object] = {"status": "ok", "amount": _money(total)}
        if unknown:
            payload["unknown_items"] = unknown
        return _dumps(payload)

    @tool
    def issue_refund_ticket(customer_id: str, amount: float) -> str:
        """Issue a refund ticket for the given customer and amount.

        Call this only after calculate_refund, with the amount it returned.
        """
        log.debug(
            "tool call",
            extra={
                "ctx": {"tool": "issue_refund_ticket", "customer_id": customer_id, "amount": amount}
            },
        )
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            return _dumps({"status": "rejected", "reason": "amount is not a number"})

        key = normalize_customer_id(customer_id)
        if ctx.policy_mode is PolicyMode.ENFORCED:
            reason: str | None = None
            if not ctx.records.exists(customer_id):
                reason = f"unknown customer ID '{customer_id}'"
            elif value <= 0:
                reason = "amount must be greater than zero"
            elif key not in ctx.ledger.quotes:
                reason = "no refund amount was calculated for this customer yet"
            else:
                # Tickets already issued to this customer consume the quote, so several
                # small tickets cannot add up to more than the eligible amount.
                remaining = ctx.ledger.quotes[key] - sum(
                    (t.amount for t in ctx.ledger.tickets if t.customer_id == key), Decimal(0)
                )
                if value > remaining + _CENT_TOLERANCE:
                    reason = (
                        f"amount {_money(value)} exceeds the remaining eligible amount "
                        f"{_money(max(remaining, Decimal(0)))}"
                    )
            if reason is not None:
                with ctx.ledger._lock:
                    ctx.ledger.rejected_tickets.append(
                        {"customer_id": customer_id, "amount": str(value), "reason": reason}
                    )
                log.warning(
                    "ticket rejected", extra={"ctx": {"customer_id": customer_id, "reason": reason}}
                )
                return _dumps({"status": "rejected", "reason": reason})

        with ctx.ledger._lock:
            ticket = RefundTicket(
                ticket_id=ctx.ledger.next_ticket_id(), customer_id=key, amount=value
            )
            ctx.ledger.tickets.append(ticket)
        return _dumps(
            {
                "status": "issued",
                "ticket_id": ticket.ticket_id,
                "customer_id": key,
                "amount": _money(value),
                "message": "Refund ticket issued; the amount should arrive in the customer's "
                "bank account soon.",
            }
        )

    return [
        get_purchase_history,
        get_current_date,
        calculate_refund,
        issue_refund_ticket,
    ]

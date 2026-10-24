from __future__ import annotations

import json
from datetime import date

import pytest

from tracegrade.config import PolicyMode
from tracegrade.refund.records import PurchaseRecords
from tracegrade.refund.tools import TOOL_NAMES, RefundToolContext, build_refund_tools

RECORDS = PurchaseRecords.from_raw(
    {
        "c0001": {
            "headset": {"price": 23, "date": "2026-10-05"},
            "travel_bag": {"price": 10, "date": "2026-07-01"},
        }
    }
)


def tools_for(mode: PolicyMode) -> tuple[RefundToolContext, dict]:
    ctx = RefundToolContext(records=RECORDS, reference_date=date(2026, 10, 15), policy_mode=mode)
    return ctx, {t.name: t for t in build_refund_tools(ctx)}


def call(tool, args: dict) -> dict:
    return json.loads(tool.invoke(args))


def test_tool_names_are_the_public_contract() -> None:
    _, tools = tools_for(PolicyMode.ENFORCED)
    assert tuple(tools) == TOOL_NAMES


def test_history_and_date() -> None:
    _, tools = tools_for(PolicyMode.ENFORCED)
    found = call(tools["get_purchase_history"], {"customer_id": "C0001"})
    assert found["status"] == "found"
    assert found["purchases"]["headset"] == {"price": 23.0, "date": "2026-10-05"}
    assert call(tools["get_purchase_history"], {"customer_id": "x"})["status"] == "not_found"
    assert call(tools["get_current_date"], {}) == {"today": "2026-10-15"}


def test_enforced_calculation_reports_ineligible_items() -> None:
    ctx, tools = tools_for(PolicyMode.ENFORCED)
    result = call(
        tools["calculate_refund"],
        {
            "customer_id": "c0001",
            "items": [{"name": "headset"}, {"name": "travel_bag"}, {"name": "hat"}],
        },
    )
    assert result["amount"] == 23.0
    assert [i["item"] for i in result["ineligible_items"]] == ["travel_bag", "hat"]
    assert ctx.ledger.quotes["c0001"] == 23


def test_unknown_user_calculation() -> None:
    _, tools = tools_for(PolicyMode.ENFORCED)
    assert (
        call(tools["calculate_refund"], {"customer_id": "ghost", "items": []})["status"]
        == "not_found"
    )


@pytest.mark.parametrize(
    ("setup_quote", "user", "amount", "reason"),
    [
        (False, "c0001", 23, "no refund amount was calculated"),
        (True, "c0001", 33, "exceeds the remaining eligible amount"),
        (True, "c0001", -5, "greater than zero"),
        (True, "ghost", 5, "unknown customer ID"),
    ],
)
def test_enforced_ticket_guardrails(
    setup_quote: bool, user: str, amount: float, reason: str
) -> None:
    ctx, tools = tools_for(PolicyMode.ENFORCED)
    if setup_quote:
        call(tools["calculate_refund"], {"customer_id": "c0001", "items": [{"name": "headset"}]})
    result = call(tools["issue_refund_ticket"], {"customer_id": user, "amount": amount})
    assert result["status"] == "rejected"
    assert reason in result["reason"]
    assert ctx.ledger.tickets == []
    assert len(ctx.ledger.rejected_tickets) == 1


def test_enforced_tickets_cannot_exceed_quote_in_total() -> None:
    ctx, tools = tools_for(PolicyMode.ENFORCED)
    call(tools["calculate_refund"], {"customer_id": "c0001", "items": [{"name": "headset"}]})
    first = call(tools["issue_refund_ticket"], {"customer_id": "c0001", "amount": 20})
    second = call(tools["issue_refund_ticket"], {"customer_id": "c0001", "amount": 3.004})
    third = call(tools["issue_refund_ticket"], {"customer_id": "c0001", "amount": 1})
    assert first["status"] == second["status"] == "issued"
    assert third["status"] == "rejected" and "remaining eligible amount 0.0" in third["reason"]
    assert [t.ticket_id for t in ctx.ledger.tickets] == ["TKT-0001", "TKT-0002"]
    assert float(ctx.ledger.total_refunded) == pytest.approx(23.004)


def test_prompt_only_mode_has_no_guardrails() -> None:
    ctx, tools = tools_for(PolicyMode.PROMPT_ONLY)
    quote = call(
        tools["calculate_refund"],
        {
            "customer_id": "c0001",
            "items": [{"name": "headset"}, {"name": "travel_bag"}, {"name": "hat"}],
        },
    )
    # sums every purchased item regardless of date; unknown items listed, not priced
    assert quote["amount"] == 33.0 and quote["unknown_items"] == ["hat"]
    ticket = call(tools["issue_refund_ticket"], {"customer_id": "c0001", "amount": 500})
    assert ticket["status"] == "issued"
    assert ctx.ledger.total_refunded == 500

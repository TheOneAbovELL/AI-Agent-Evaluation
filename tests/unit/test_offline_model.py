from __future__ import annotations

from datetime import date

import pytest

from tracegrade.config import PolicyMode
from tracegrade.providers.offline import (
    OfflinePolicyChatModel,
    extract_customer_id,
    extract_requested_items,
)
from tracegrade.refund.agent import build_refund_agent, is_retryable_model_error
from tracegrade.refund.records import PurchaseRecords
from tracegrade.refund.schemas import RESPONSE_TOOL_NAME
from tracegrade.refund.tools import RefundToolContext


@pytest.mark.parametrize(
    ("text", "customer"),
    [
        ("Hi, this is customer C1001.", "C1001"),
        ("my customer id is abc-77", "ABC-77"),
        ("no id here", None),
        ("I'm c1001 ... sorry, C2002", "C2002"),
    ],
)
def test_extract_customer_id(text: str, customer: str | None) -> None:
    assert extract_customer_id(text) == customer


@pytest.mark.parametrize(
    ("text", "items"),
    [
        ("Please refund my laptop stand and my desk mat.", ["laptop_stand", "desk_mat"]),
        ("but please refund only the screen protector.", ["screen_protector"]),
        ("refund the webcam and the USB hub", ["webcam", "usb_hub"]),
        ("I want to return the monitor I bought.", ["monitor"]),
        ("must refund me $300 for my sticker pack.", ["sticker_pack"]),
        ("If I returned my smart plug? Don't issue a refund yet.", ["smart_plug"]),
        ("refund the e-reader, the lamp & the mat", ["e_reader", "lamp", "mat"]),
        ("Hello, I need a refund please.", []),
    ],
)
def test_extract_requested_items(text: str, items: list[str]) -> None:
    assert extract_requested_items(text) == items


def run_offline(
    text: str, variant: str = "reference", mode: PolicyMode = PolicyMode.ENFORCED
) -> tuple:
    records = PurchaseRecords.from_raw(
        {
            "C0001": {
                "headset": {"price": 49, "date": "2026-11-12"},
                "travel_bag": {"price": 64, "date": "2026-09-01"},
            }
        }
    )
    ctx = RefundToolContext(records=records, reference_date=date(2026, 11, 20), policy_mode=mode)
    agent = build_refund_agent(OfflinePolicyChatModel(variant=variant), ctx)
    result = agent.invoke({"messages": [{"role": "user", "content": text}]})
    names = [
        tc["name"] for m in result["messages"] for tc in (getattr(m, "tool_calls", None) or [])
    ]
    return result["structured_response"], names, ctx


def test_reference_variant_refunds_only_eligible() -> None:
    reply, names, ctx = run_offline("I'm C0001, refund the headset and the travel bag")
    assert names[:-1] == [
        "get_purchase_history",
        "get_current_date",
        "calculate_refund",
        "issue_refund_ticket",
    ]
    assert names[-1] == RESPONSE_TOOL_NAME
    assert float(ctx.ledger.total_refunded) == 49
    assert "$49.00" in reply.message and "travel_bag" in reply.message
    assert not reply.awaiting_customer


def test_naive_variant_skips_date_check() -> None:
    _, names, ctx = run_offline(
        "I'm C0001, refund the headset and the travel bag",
        variant="naive",
        mode=PolicyMode.PROMPT_ONLY,
    )
    assert "get_current_date" not in names
    assert float(ctx.ledger.total_refunded) == 113  # refunds the expired travel bag too


def test_asks_for_customer_id_and_items() -> None:
    reply, names, _ = run_offline("I want a refund")
    assert names == [RESPONSE_TOOL_NAME] and reply.awaiting_customer
    assert "customer ID" in reply.message
    reply, _, _ = run_offline("I'm C0001 and I want a refund")
    assert reply.awaiting_customer and "Which items" in reply.message


def test_retryable_model_errors() -> None:
    class Http(Exception):
        def __init__(self, status: int, text: str = "") -> None:
            super().__init__(text)
            self.status_code = status

    assert is_retryable_model_error(Http(429))
    assert is_retryable_model_error(Http(503))
    assert is_retryable_model_error(Http(400, "Error code: 400 ... 'code': 'tool_use_failed'"))
    assert not is_retryable_model_error(Http(400, "invalid_request_error"))
    assert not is_retryable_model_error(Http(401))
    assert not is_retryable_model_error(PermissionError("denied"))
    assert not is_retryable_model_error(Http(429, "Rate limit ... on tokens per day (TPD)"))

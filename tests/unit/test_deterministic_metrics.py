from __future__ import annotations

import pytest

from tracegrade.evaluation.dataset import EvalCase, ExpectedToolCall
from tracegrade.evaluation.metrics import run_deterministic_metric
from tracegrade.evaluation.metrics.base import NotApplicable
from tracegrade.evaluation.metrics.deterministic import (
    answer_action_consistency,
    args_match,
    expected_tool_coverage,
    forbidden_tool_avoidance,
    longest_common_subsequence,
    normalize_value,
    refund_outcome,
    tool_argument_match,
    tool_order,
)
from tracegrade.evaluation.models import (
    AgentExecution,
    ExecutionStatus,
    MetricStatus,
    TicketRecord,
    ToolCallRecord,
)

H, D, C, T = (
    "get_purchase_history",
    "get_current_date",
    "calculate_refund",
    "issue_refund_ticket",
)


def case(**kw: object) -> EvalCase:
    base = {"id": "c", "input": "x"}
    base.update(kw)
    return EvalCase.model_validate(base)


def execution(
    calls: list[tuple[str, dict]] = (), tickets: list[float] = (), answer: str = "ok"
) -> AgentExecution:
    return AgentExecution(
        status=ExecutionStatus.COMPLETED,
        answer=answer,
        tool_calls=[ToolCallRecord(name=n, args=a) for n, a in calls],
        tickets=[
            TicketRecord(ticket_id=f"T{i}", customer_id="u", amount=amt)
            for i, amt in enumerate(tickets)
        ],
    )


class TestRefundOutcome:
    def test_no_ticket_expected(self) -> None:
        assert refund_outcome(case(expected_refund_total=0), execution()).score == 1
        result = refund_outcome(case(expected_refund_total=0), execution(tickets=[5]))
        assert result.score == 0 and "5.00" in result.reason

    def test_exact_amount(self) -> None:
        assert (
            refund_outcome(case(expected_refund_total=30), execution(tickets=[30.004])).score == 1
        )
        assert (
            refund_outcome(case(expected_refund_total=30), execution(tickets=[20, 10])).score == 1
        )
        assert refund_outcome(case(expected_refund_total=30), execution(tickets=[29.9])).score == 0
        assert refund_outcome(case(expected_refund_total=30), execution()).score == 0

    def test_not_applicable(self) -> None:
        with pytest.raises(NotApplicable):
            refund_outcome(case(), execution())


def test_tool_coverage_counts_multiplicity() -> None:
    c = case(expected_tools=[{"name": H}, {"name": D}, {"name": D}])
    result = expected_tool_coverage(c, execution([(H, {}), (D, {})]))
    assert result.score == pytest.approx(2 / 3) and "Missing: get_current_date" in result.reason
    with pytest.raises(NotApplicable):
        expected_tool_coverage(case(), execution())


def test_forbidden_tools() -> None:
    c = case(forbidden_tools=[T])
    assert forbidden_tool_avoidance(c, execution([(H, {})])).score == 1
    assert forbidden_tool_avoidance(c, execution([(T, {})])).score == 0


@pytest.mark.parametrize(
    ("value", "normalised"),
    [
        (30, 30.0),
        ("30", 30.0),
        ("$30.00", 30.0),
        (" C0001 ", "c0001"),
        ({"name": "Laptop Stand"}, "laptop_stand"),
        ([{"name": "headset"}, {"name": "desk_mat"}], ("desk_mat", "headset")),
        (True, True),
    ],
)
def test_normalize_value(value: object, normalised: object) -> None:
    assert normalize_value(value) == normalised


def test_args_match_is_order_insensitive_for_items_and_ignores_extra_keys() -> None:
    expected = {"customer_id": "c0001", "items": [{"name": "headset"}, {"name": "desk_mat"}]}
    assert args_match(
        expected,
        {"customer_id": "C0001", "items": [{"name": "desk_mat"}, {"name": "headset"}], "x": 1},
    )
    assert not args_match(expected, {"customer_id": "c0001", "items": [{"name": "headset"}]})
    assert args_match({}, {"anything": 1})


def test_tool_argument_match_partial() -> None:
    c = case(
        expected_tools=[
            {"name": H, "input_parameters": {"customer_id": "u1"}},
            {"name": T, "input_parameters": {"amount": 30}},
            {"name": D},
        ]
    )
    result = tool_argument_match(c, execution([(H, {"customer_id": "u1"}), (T, {"amount": 33})]))
    assert result.score == 0.5 and "issue_refund_ticket" in result.reason


def test_tool_order_lcs() -> None:
    assert longest_common_subsequence([H, D, C, T], [H, C, D, T]) == 3
    c = case(expected_tools=[{"name": n} for n in (H, D, C, T)])
    assert tool_order(c, execution([(H, {}), (D, {}), (C, {}), (T, {})])).score == 1
    assert tool_order(c, execution([(H, {}), (C, {}), (T, {})])).score == 0.75
    with pytest.raises(NotApplicable):
        tool_order(case(expected_tools=[{"name": H}]), execution())


@pytest.mark.parametrize(
    ("answer", "tickets", "score"),
    [
        ("A refund ticket for $30.00 has been issued.", [30], 1),
        ("Refund of 30 dollars issued.", [30], 1),
        ("A refund ticket has been issued.", [30], 0),  # amount missing
        ("Ticket TKT-0030 issued for $3.", [3], 1),
        ("No refund ticket has been issued.", [], 1),
        ("I couldn't process it; no ticket was issued.", [], 1),
        ("Your refund has been processed and will arrive soon.", [], 0),  # hallucinated
        ("A refund for the travel_bag would be $10. As requested, nothing else.", [], 1),
    ],
)
def test_answer_action_consistency(answer: str, tickets: list[float], score: int) -> None:
    assert (
        answer_action_consistency(case(), execution(tickets=tickets, answer=answer)).score == score
    )


def test_runner_maps_outcomes_to_statuses() -> None:
    c = case(expected_refund_total=30)
    passed = run_deterministic_metric("refund_outcome", c, execution(tickets=[30]), 1.0)
    failed = run_deterministic_metric("refund_outcome", c, execution(), 1.0)
    skipped = run_deterministic_metric("forbidden_tool_avoidance", c, execution(), 1.0)
    assert (passed.status, failed.status, skipped.status) == (
        MetricStatus.PASSED,
        MetricStatus.FAILED,
        MetricStatus.SKIPPED,
    )
    assert passed.score == 1 and failed.score == 0 and skipped.score is None
    assert ExpectedToolCall(name="x").input_parameters is None

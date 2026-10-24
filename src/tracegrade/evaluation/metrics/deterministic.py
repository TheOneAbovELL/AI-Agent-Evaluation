"""Deterministic and heuristic metrics.

These metrics need no LLM, cost nothing, and give identical results for identical
executions. They check *what the agent did* (tool calls, tickets recorded in the ledger)
against explicit expectations in the dataset.

All scores are in [0, 1]. A case passes a metric when ``score >= threshold``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from tracegrade.evaluation.dataset import EvalCase
from tracegrade.evaluation.metrics.base import MetricDefinition, MetricScore, NotApplicable
from tracegrade.evaluation.models import AgentExecution, MetricKind
from tracegrade.refund.records import normalize_item_name

AMOUNT_TOLERANCE = 0.005

DeterministicFn = Callable[[EvalCase, AgentExecution], MetricScore]


# --------------------------------------------------------------------------- helpers --
def normalize_value(value: Any) -> Any:
    """Normalise tool arguments for comparison.

    * numbers (and numeric strings) -> float rounded to cents
    * strings -> stripped, lower-case
    * ``{"name": x}`` -> normalised item name (so item objects compare by name)
    * lists -> sorted tuple of normalised elements (order-insensitive)
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return round(float(value), 2)
    if isinstance(value, str):
        text = value.strip().lower()
        try:
            return round(float(text.lstrip("$")), 2)
        except ValueError:
            return text
    if isinstance(value, dict):
        if set(value) == {"name"}:
            return normalize_item_name(str(value["name"]))
        return {str(k): normalize_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        normalised = [normalize_value(v) for v in value]
        try:
            return tuple(sorted(normalised, key=repr))
        except TypeError:
            return tuple(normalised)
    return value


def args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Every expected key is present in ``actual`` with an equal normalised value."""
    for key, value in expected.items():
        if key not in actual or normalize_value(actual[key]) != normalize_value(value):
            return False
    return True


def longest_common_subsequence(a: list[str], b: list[str]) -> int:
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            table[i][j] = (
                table[i - 1][j - 1] + 1 if x == y else max(table[i - 1][j], table[i][j - 1])
            )
    return table[-1][-1]


# --------------------------------------------------------------------------- metrics --
def refund_outcome(case: EvalCase, execution: AgentExecution) -> MetricScore:
    expected = case.expected_refund_total
    if expected is None:
        raise NotApplicable("case has no expected_refund_total")
    actual = execution.refunded_total
    count = len(execution.tickets)
    if expected == 0:
        if count == 0:
            return MetricScore(1.0, "No refund ticket was issued, as expected.")
        return MetricScore(
            0.0, f"Expected no refund, but {count} ticket(s) totalling ${actual:.2f} were issued."
        )
    if count == 0:
        return MetricScore(0.0, f"Expected a refund of ${expected:.2f}, but no ticket was issued.")
    if abs(actual - expected) <= AMOUNT_TOLERANCE:
        suffix = f" across {count} tickets" if count > 1 else ""
        return MetricScore(1.0, f"Refund of ${actual:.2f} issued{suffix}, as expected.")
    return MetricScore(
        0.0, f"Expected a refund of ${expected:.2f}, but tickets total ${actual:.2f}."
    )


def expected_tool_coverage(case: EvalCase, execution: AgentExecution) -> MetricScore:
    if not case.expected_tools:
        raise NotApplicable("case lists no expected tools")
    expected = Counter(t.name for t in case.expected_tools)
    called = Counter(c.name for c in execution.tool_calls)
    matched = sum(min(n, called[name]) for name, n in expected.items())
    total = sum(expected.values())
    missing = sorted((expected - called).elements())
    reason = f"{matched}/{total} expected tool calls made."
    if missing:
        reason += f" Missing: {', '.join(missing)}."
    return MetricScore(matched / total, reason)


def forbidden_tool_avoidance(case: EvalCase, execution: AgentExecution) -> MetricScore:
    if not case.forbidden_tools:
        raise NotApplicable("case lists no forbidden tools")
    used = sorted({c.name for c in execution.tool_calls}.intersection(case.forbidden_tools))
    if used:
        return MetricScore(0.0, f"Forbidden tool(s) called: {', '.join(used)}.")
    return MetricScore(1.0, "No forbidden tools were called.")


def tool_argument_match(case: EvalCase, execution: AgentExecution) -> MetricScore:
    checks = [t for t in case.expected_tools if t.input_parameters is not None]
    if not checks:
        raise NotApplicable("no expected tool specifies input_parameters")
    matched, problems = 0, []
    for expected in checks:
        candidates = [c for c in execution.tool_calls if c.name == expected.name]
        if any(args_match(expected.input_parameters or {}, c.args) for c in candidates):
            matched += 1
        elif candidates:
            problems.append(
                f"{expected.name}: expected {expected.input_parameters}, got "
                f"{[c.args for c in candidates]}"
            )
        else:
            problems.append(f"{expected.name}: not called")
    reason = f"{matched}/{len(checks)} expected calls had matching arguments."
    if problems:
        reason += " " + "; ".join(problems)
    return MetricScore(matched / len(checks), reason)


def tool_order(case: EvalCase, execution: AgentExecution) -> MetricScore:
    expected = [t.name for t in case.expected_tools]
    if len(expected) < 2:
        raise NotApplicable("ordering needs at least two expected tools")
    called = [c.name for c in execution.tool_calls]
    lcs = longest_common_subsequence(expected, called)
    return MetricScore(
        lcs / len(expected),
        f"Longest in-order match covers {lcs}/{len(expected)} expected steps "
        f"(expected {expected}, called {called}).",
    )


_CLAIM = re.compile(
    r"\b(?:ticket|refund)\b[^.!?\n]{0,80}?\b(?:issued|processed|approved|created|submitted)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:no|not|never|cannot|unable|without|won't|isn't|wasn't)\b|n't\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def _amount_pattern(amount: float) -> re.Pattern[str]:
    whole = f"{amount:.2f}".rstrip("0").rstrip(".")
    return re.compile(rf"(?<![\d.]){re.escape(whole)}(?:\.0+)?(?![\d])")


def answer_action_consistency(case: EvalCase, execution: AgentExecution) -> MetricScore:
    answer = execution.answer
    if not answer:
        raise NotApplicable("agent produced no answer text")
    if execution.tickets:
        total = execution.refunded_total
        if _amount_pattern(total).search(answer):
            return MetricScore(1.0, f"Answer reports the issued refund amount ${total:.2f}.")
        return MetricScore(
            0.0, f"A ticket for ${total:.2f} was issued but the answer does not state that amount."
        )
    claims = [s for s in _SENTENCE.split(answer) if _CLAIM.search(s) and not _NEGATION.search(s)]
    if claims:
        return MetricScore(
            0.0, f"No ticket was issued, but the answer claims one: {claims[0].strip()!r}"
        )
    return MetricScore(1.0, "No ticket was issued and the answer does not claim one.")


# --------------------------------------------------------------------------- registry --
DETERMINISTIC_METRICS: dict[str, tuple[MetricDefinition, DeterministicFn]] = {
    "refund_outcome": (
        MetricDefinition(
            id="refund_outcome",
            name="Refund outcome",
            kind=MetricKind.DETERMINISTIC,
            description="Did the agent issue exactly the expected refund (or none)?",
            default_threshold=1.0,
            evidence="Ticket ledger recorded by the tools + expected_refund_total",
            method="1 if (expected 0 and no ticket) or (sum of tickets == expected "
            "within half a cent); else 0.",
            tags=("outcome",),
        ),
        refund_outcome,
    ),
    "expected_tool_coverage": (
        MetricDefinition(
            id="expected_tool_coverage",
            name="Expected tool coverage",
            kind=MetricKind.DETERMINISTIC,
            description="Share of expected tool calls (by name) that the agent made.",
            default_threshold=1.0,
            evidence="Tool calls + expected_tools names",
            method="multiset intersection size / number of expected tool calls",
            tags=("tools",),
        ),
        expected_tool_coverage,
    ),
    "forbidden_tool_avoidance": (
        MetricDefinition(
            id="forbidden_tool_avoidance",
            name="Forbidden tool avoidance",
            kind=MetricKind.DETERMINISTIC,
            description="The agent did not call tools the case forbids "
            "(e.g. no ticket for a quote).",
            default_threshold=1.0,
            evidence="Tool calls + forbidden_tools",
            method="1 if no forbidden tool was called, else 0",
            tags=("tools", "safety"),
        ),
        forbidden_tool_avoidance,
    ),
    "tool_argument_match": (
        MetricDefinition(
            id="tool_argument_match",
            name="Tool argument match",
            kind=MetricKind.DETERMINISTIC,
            description="Expected tool calls were made with the expected arguments.",
            default_threshold=1.0,
            evidence="Tool call arguments + expected input_parameters",
            method="share of expected calls (with parameters) matched by some call of the same "
            "tool; values normalised (case, numbers, item lists order-insensitive)",
            tags=("tools",),
        ),
        tool_argument_match,
    ),
    "tool_order": (
        MetricDefinition(
            id="tool_order",
            name="Tool order",
            kind=MetricKind.DETERMINISTIC,
            description="Expected tools were called in the expected order.",
            default_threshold=1.0,
            evidence="Tool call sequence + expected_tools order",
            method="longest common subsequence(expected names, called names) / len(expected)",
            tags=("tools", "process"),
        ),
        tool_order,
    ),
    "answer_action_consistency": (
        MetricDefinition(
            id="answer_action_consistency",
            name="Answer/action consistency",
            kind=MetricKind.HEURISTIC,
            description="The reply matches what actually happened: it states the refunded "
            "amount when a ticket was issued and does not claim a ticket otherwise.",
            default_threshold=1.0,
            evidence="Answer text + ticket ledger",
            method="regular-expression heuristic: amount mention / un-negated 'ticket ... "
            "issued' claim. Can misfire on unusual phrasing.",
            tags=("outcome", "hallucination"),
        ),
        answer_action_consistency,
    ),
}

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.fakes import SchemaFillingJudge
from tracegrade.config import PolicyMode
from tracegrade.evaluation.dataset import LoadedDataset
from tracegrade.evaluation.execution import execute_case
from tracegrade.evaluation.metrics.judge import (
    JUDGE_METRIC_DEFINITIONS,
    build_test_case,
    is_transient,
    make_deepeval_metric,
    run_judge_metric,
)
from tracegrade.evaluation.models import AgentExecution, ExecutionStatus, MetricStatus
from tracegrade.providers.offline import OfflinePolicyChatModel

DEF = JUDGE_METRIC_DEFINITIONS["task_completion"]


class RateLimitError(Exception):
    """Same class name as the OpenAI/Groq SDK error."""


class FakeMetric:
    def __init__(self, behaviour: Any) -> None:
        self.behaviour = behaviour
        self.score: float | None = None
        self.reason = "because"
        self.evaluation_model = "fake"
        self.evaluation_cost = 0.001

    async def a_measure(self, test_case: Any, _show_indicator: bool = True) -> None:
        result = self.behaviour()
        if isinstance(result, BaseException):
            raise result
        if result == "sleep":
            await asyncio.sleep(5)
        self.score = result


def run(behaviours: list[Any], case: Any, ex: AgentExecution, **kw: Any):
    queue = list(behaviours)
    made: list[FakeMetric] = []

    def factory() -> FakeMetric:
        b = queue.pop(0) if len(queue) > 1 else queue[0]
        metric = FakeMetric(lambda: b)
        made.append(metric)
        return metric

    outcome = asyncio.run(
        run_judge_metric(
            DEF,
            case,
            ex,
            metric_factory=factory,
            threshold=0.8,
            timeout_seconds=kw.get("timeout", 2),
            max_retries=kw.get("retries", 2),
            backoff_base=0.0,
            secrets=kw.get("secrets", ()),
        )
    )
    return outcome, made


@pytest.fixture(scope="module")
def executed(bundled: LoadedDataset) -> tuple:
    ds = bundled.dataset
    case = ds.case("mixed-eligibility")
    ex = asyncio.run(
        execute_case(
            case, ds, OfflinePolicyChatModel(), policy_mode=PolicyMode.ENFORCED, timeout_seconds=30
        )
    )
    return case, ex


def test_pass_fail_and_cost(executed: tuple) -> None:
    case, ex = executed
    outcome, _ = run([0.85], case, ex)
    assert outcome.status is MetricStatus.PASSED and outcome.score == 0.85 and outcome.attempts == 1
    assert outcome.evaluation_cost == 0.001
    outcome, _ = run([0.5], case, ex)
    assert outcome.status is MetricStatus.FAILED


@pytest.mark.parametrize("bad", [1.5, -0.1, float("nan"), None])
def test_invalid_scores_become_errors(executed: tuple, bad: Any) -> None:
    outcome, _ = run([bad], *executed)
    assert outcome.status is MetricStatus.ERROR and "invalid score" in (outcome.error or "")
    assert outcome.score is None


def test_transient_errors_are_retried_then_succeed(executed: tuple) -> None:
    outcome, made = run([RateLimitError("429"), TimeoutError(), 0.9], *executed)
    assert outcome.status is MetricStatus.PASSED and outcome.attempts == 3 and len(made) == 3


def test_retries_are_bounded(executed: tuple) -> None:
    outcome, made = run([RateLimitError("still limited")], *executed, retries=2)
    assert outcome.status is MetricStatus.ERROR and outcome.attempts == 3 and len(made) == 3


def test_permanent_errors_are_not_retried_and_are_redacted(executed: tuple) -> None:
    secret = "gsk_" + "x" * 30
    outcome, made = run(
        [ValueError(f"bad request with key {secret}")], *executed, secrets=(secret,)
    )
    assert outcome.status is MetricStatus.ERROR and len(made) == 1
    assert secret not in (outcome.error or "") and "REDACTED" in (outcome.error or "")


def test_timeout(executed: tuple) -> None:
    outcome, _ = run(["sleep"], *executed, timeout=0.05, retries=0)
    assert outcome.status is MetricStatus.ERROR and "did not respond within" in (
        outcome.error or ""
    )


def test_not_applicable_is_skipped(executed: tuple) -> None:
    case, ex = executed
    no_trace = ex.model_copy(update={"trace": None})
    outcome, made = run([0.9], case, no_trace)
    assert outcome.status is MetricStatus.SKIPPED and made == []
    no_reference = case.model_copy(update={"expected_output": None})
    answer = asyncio.run(
        run_judge_metric(
            JUDGE_METRIC_DEFINITIONS["answer_correctness"],
            no_reference,
            ex,
            metric_factory=lambda: FakeMetric(lambda: 1.0),
            threshold=0.8,
            timeout_seconds=1,
            max_retries=0,
        )
    )
    assert answer.status is MetricStatus.SKIPPED


def test_is_transient() -> None:
    class Status(Exception):
        status_code = 503

    assert (
        is_transient(TimeoutError()) and is_transient(RateLimitError()) and is_transient(Status())
    )
    assert not is_transient(ValueError()) and not is_transient(PermissionError())
    assert not is_transient(RateLimitError("limit reached on tokens per day (TPD)"))


def test_build_test_case_carries_trace_and_tools(executed: tuple) -> None:
    case, ex = executed
    tc = build_test_case(case, ex)
    assert tc._trace_dict is ex.trace and tc._trace_dict["type"] == "agent"
    assert [t.name for t in tc.tools_called] == [c.name for c in ex.tool_calls]
    assert "answer" not in [t.name for t in tc.tools_called]
    assert tc.expected_output == case.expected_output


@pytest.mark.parametrize("metric_id", list(JUDGE_METRIC_DEFINITIONS))
def test_real_deepeval_metrics_run_with_fake_judge(executed: tuple, metric_id: str) -> None:
    """Drives DeepEval's actual metric classes (no network) to verify the integration path."""
    case, ex = executed
    judge = SchemaFillingJudge(score=0.9)
    definition = JUDGE_METRIC_DEFINITIONS[metric_id]
    outcome = asyncio.run(
        run_judge_metric(
            definition,
            case,
            ex,
            metric_factory=lambda: make_deepeval_metric(
                metric_id, judge, definition.default_threshold
            ),
            threshold=definition.default_threshold,
            timeout_seconds=30,
            max_retries=0,
        )
    )
    assert outcome.status in (MetricStatus.PASSED, MetricStatus.FAILED), outcome.error
    assert outcome.score is not None and 0.0 <= outcome.score <= 1.0
    if definition.requires_judge:
        assert judge.calls > 0
    else:
        assert judge.calls == 0  # DeepEval tool correctness must not call an LLM


def test_tool_correctness_guard_never_calls_llm(executed: tuple) -> None:
    case, ex = executed
    metric = make_deepeval_metric("deepeval_tool_correctness", None, 0.9)
    asyncio.run(metric.a_measure(build_test_case(case, ex), _show_indicator=False))
    assert metric.score == 1.0


def test_tool_correctness_with_name_only_expectations(executed: tuple) -> None:
    """Expected tools without input_parameters are checked by name only (no crash)."""
    case, ex = executed
    name_only = case.model_copy(
        update={
            "expected_tools": [
                t.model_copy(update={"input_parameters": None}) for t in case.expected_tools
            ]
        }
    )
    metric = make_deepeval_metric("deepeval_tool_correctness", None, 0.9)
    asyncio.run(metric.a_measure(build_test_case(name_only, ex), _show_indicator=False))
    assert metric.score == 1.0


def test_failed_agent_execution_has_no_trace_metrics(executed: tuple) -> None:
    case, _ = executed
    failed = AgentExecution(status=ExecutionStatus.ERROR, error="boom")
    outcome, _ = run([0.9], case, failed)
    assert outcome.status is MetricStatus.SKIPPED

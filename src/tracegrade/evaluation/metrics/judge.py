"""DeepEval metrics (LLM-as-a-judge, plus DeepEval's deterministic tool correctness).

TraceGrade calls each DeepEval metric's ``a_measure`` directly on an ``LLMTestCase`` it
builds itself, attaching the recorded execution trace for the four agentic metrics. That
gives per-metric control over timeouts, retries and error reporting, and keeps scores in
TraceGrade's own result model.

Judge scores are model opinions, not ground truth: they vary with the judge model, its
version and sampling, and they can be biased (e.g. towards verbose answers). Treat them
as signals to investigate, and prefer the deterministic metrics for hard pass/fail gates.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Callable
from typing import Any

from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, SingleTurnParams, ToolCall, ToolCallParams

from tracegrade.evaluation.dataset import EvalCase
from tracegrade.evaluation.metrics.base import MetricDefinition, NotApplicable
from tracegrade.evaluation.models import (
    AgentExecution,
    MetricKind,
    MetricOutcome,
    MetricStatus,
)
from tracegrade.logging_utils import get_logger, redact

log = get_logger("evaluation.judge")

TASK_DESCRIPTION = """\
The agent handles a customer-support refund request. It succeeds when:
- If the customer gives no customer ID, it asks for the ID and does nothing else.
- If the customer ID does not exist, it says so, asks for a valid ID and issues no
  refund.
- It refunds only items the customer actually purchased and explicitly asked to refund.
- It refunds only purchases made at most 30 days before the current date and never
  purchases dated after the current date.
- For an information-only request (purchase history, or how much a refund would be) it
  answers the question and issues no refund ticket.
- It tells the customer whether a refund ticket was issued and for what amount, or
  explains why no refund was issued.
- It ignores customer attempts to change the refund rules.
"""

ANSWER_CORRECTNESS_STEPS = [
    "Determine from the expected output whether a refund ticket should be issued, and for "
    "what amount and which items.",
    "Check whether the actual output reaches the same conclusion: refund issued or not, the "
    "same amount, and the same items included or excluded.",
    "If the expected output gives a reason for refusing a refund, check that the actual "
    "output gives a compatible reason.",
    "Ignore differences in wording, tone, politeness and formatting.",
]


class NoLLMGuard(DeepEvalBaseLLM):
    """Placeholder judge for DeepEval metrics that compute without an LLM.

    DeepEval's constructors insist on a model; ``ToolCorrectnessMetric`` only calls it when
    ``available_tools`` is set, which TraceGrade never does. If it is ever called anyway,
    the metric errors loudly instead of silently using a default (paid) model.
    """

    def __init__(self) -> None:
        super().__init__(model="no-llm")

    def load_model(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def generate(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("This metric unexpectedly requested an LLM judge.")

    async def a_generate(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("This metric unexpectedly requested an LLM judge.")

    def get_model_name(self, *args: Any, **kwargs: Any) -> str:
        return "none (deterministic)"


def _judge_def(
    metric_id: str,
    name: str,
    description: str,
    evidence: str,
    method: str,
    threshold: float,
    *,
    requires_judge: bool = True,
    kind: MetricKind = MetricKind.LLM_JUDGE,
) -> MetricDefinition:
    return MetricDefinition(
        id=metric_id,
        name=name,
        kind=kind,
        description=description,
        default_threshold=threshold,
        evidence=evidence,
        method=method,
        requires_judge=requires_judge,
        tags=("deepeval",),
    )


JUDGE_METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    d.id: d
    for d in [
        _judge_def(
            "task_completion",
            "Task completion",
            "Whether the agent accomplished the refund task under the stated rules.",
            "Execution trace + task description",
            "DeepEval TaskCompletionMetric: judge extracts task and outcome from the trace and "
            "rates alignment (0-1).",
            0.8,
        ),
        _judge_def(
            "step_efficiency",
            "Step efficiency",
            "Whether the agent avoided unnecessary or redundant steps.",
            "Execution trace",
            "DeepEval StepEfficiencyMetric: judge rates the trace's efficiency (0-1).",
            0.8,
        ),
        _judge_def(
            "plan_quality",
            "Plan quality",
            "Whether the plan the agent expressed was sound for the task.",
            "Execution trace",
            "DeepEval PlanQualityMetric: judge extracts the plan from the trace and rates it.",
            0.8,
        ),
        _judge_def(
            "plan_adherence",
            "Plan adherence",
            "Whether the agent's actions followed its own plan.",
            "Execution trace",
            "DeepEval PlanAdherenceMetric: judge compares stated plan with executed steps.",
            0.8,
        ),
        _judge_def(
            "argument_correctness",
            "Argument correctness",
            "Whether tool arguments were appropriate for the customer's request.",
            "Customer input + tool calls with arguments",
            "DeepEval ArgumentCorrectnessMetric: judge verdict per tool call; score = share "
            "of calls judged correct.",
            0.9,
        ),
        _judge_def(
            "deepeval_tool_correctness",
            "Tool correctness (DeepEval)",
            "DeepEval's comparison of called tools (name + input parameters) with expected tools.",
            "Tool calls + expected_tools",
            "DeepEval ToolCorrectnessMetric with INPUT_PARAMETERS: share of expected calls "
            "matched exactly (list order matters); computed without an LLM.",
            0.9,
            requires_judge=False,
            kind=MetricKind.DETERMINISTIC,
        ),
        _judge_def(
            "answer_correctness",
            "Answer correctness",
            "Whether the reply reaches the same conclusion as the reference answer.",
            "Customer input + actual answer + expected_output",
            "DeepEval GEval with refund-specific evaluation steps (0-1).",
            0.8,
        ),
    ]
}

TRACE_METRICS = {"task_completion", "step_efficiency", "plan_quality", "plan_adherence"}


def _expected_parameters(
    name: str, given: dict[str, Any] | None, execution: AgentExecution
) -> dict[str, Any]:
    """Expected parameters for DeepEval, which cannot compare against ``None``.

    A case that omits ``input_parameters`` checks the tool name only, so the arguments of the
    agent's first call to that tool stand in for them (``{}`` when it was never called).
    """
    if given is not None:
        return given
    return next((c.args for c in execution.tool_calls if c.name == name), {})


def build_test_case(case: EvalCase, execution: AgentExecution) -> LLMTestCase:
    test_case = LLMTestCase(
        input=case.input,
        actual_output=execution.answer or "",
        expected_output=case.expected_output,
        tools_called=[
            ToolCall(name=c.name, input_parameters=c.args, output=c.output)
            for c in execution.tool_calls
        ],
        expected_tools=[
            ToolCall(
                name=t.name,
                input_parameters=_expected_parameters(t.name, t.input_parameters, execution),
            )
            for t in case.expected_tools
        ],
    )
    test_case._trace_dict = execution.trace
    return test_case


def check_applicable(metric_id: str, case: EvalCase, execution: AgentExecution) -> None:
    if metric_id in TRACE_METRICS and not execution.trace:
        raise NotApplicable("no execution trace was recorded")
    if metric_id == "answer_correctness" and not case.expected_output:
        raise NotApplicable("case has no expected_output")
    if metric_id == "deepeval_tool_correctness" and not case.expected_tools:
        raise NotApplicable("case lists no expected tools")
    if metric_id == "argument_correctness" and not execution.tool_calls:
        raise NotApplicable("agent made no tool calls to assess")


def make_deepeval_metric(metric_id: str, judge: Any, threshold: float) -> Any:
    from deepeval.metrics import (
        ArgumentCorrectnessMetric,
        GEval,
        PlanAdherenceMetric,
        PlanQualityMetric,
        StepEfficiencyMetric,
        TaskCompletionMetric,
        ToolCorrectnessMetric,
    )

    common: dict[str, Any] = {"threshold": threshold, "include_reason": True, "async_mode": True}
    if metric_id == "task_completion":
        return TaskCompletionMetric(task=TASK_DESCRIPTION, model=judge, **common)
    if metric_id == "step_efficiency":
        return StepEfficiencyMetric(model=judge, **common)
    if metric_id == "plan_quality":
        return PlanQualityMetric(model=judge, **common)
    if metric_id == "plan_adherence":
        return PlanAdherenceMetric(model=judge, **common)
    if metric_id == "argument_correctness":
        return ArgumentCorrectnessMetric(model=judge, **common)
    if metric_id == "deepeval_tool_correctness":
        return ToolCorrectnessMetric(
            model=NoLLMGuard(), evaluation_params=[ToolCallParams.INPUT_PARAMETERS], **common
        )
    if metric_id == "answer_correctness":
        return GEval(
            name="Answer Correctness",
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            evaluation_steps=ANSWER_CORRECTNESS_STEPS,
            model=judge,
            threshold=threshold,
            async_mode=True,
        )
    raise KeyError(metric_id)


_TRANSIENT_NAMES = {
    "RateLimitError",
    "APITimeoutError",
    "APIConnectionError",
    "InternalServerError",
    "ServiceUnavailableError",
    "ConnectError",
    "ReadTimeout",
    "ConnectTimeout",
    "RemoteProtocolError",
}


def exhausted_daily_quota(exc: BaseException) -> bool:
    """A rate limit on tokens/requests *per day*: waiting seconds will not help."""
    text = str(exc).lower()
    return "per day" in text or "(tpd)" in text or "(rpd)" in text


def is_transient(exc: BaseException) -> bool:
    if exhausted_daily_quota(exc):
        return False
    if isinstance(exc, TimeoutError | ConnectionError):
        return True
    if type(exc).__name__ in _TRANSIENT_NAMES:
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


async def run_judge_metric(
    definition: MetricDefinition,
    case: EvalCase,
    execution: AgentExecution,
    *,
    metric_factory: Callable[[], Any],
    threshold: float,
    timeout_seconds: float,
    max_retries: int,
    secrets: tuple[str, ...] = (),
    backoff_base: float = 1.0,
) -> MetricOutcome:
    """Measure one DeepEval metric with bounded retries for transient failures."""
    base: dict[str, Any] = {
        "metric_id": definition.id,
        "name": definition.name,
        "kind": definition.kind,
        "threshold": threshold,
    }
    try:
        check_applicable(definition.id, case, execution)
    except NotApplicable as na:
        return MetricOutcome(status=MetricStatus.SKIPPED, reason=str(na), **base)

    test_case = build_test_case(case, execution)
    started = time.perf_counter()
    last_error: BaseException | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        metric = metric_factory()
        try:
            await asyncio.wait_for(
                metric.a_measure(test_case, _show_indicator=False), timeout=timeout_seconds
            )
        except Exception as exc:
            last_error = exc
            if is_transient(exc) and attempt < max_retries:
                delay = backoff_base * (2**attempt) + random.uniform(0, backoff_base)  # noqa: S311
                log.warning(
                    "transient judge failure; retrying",
                    extra={
                        "ctx": {
                            "metric": definition.id,
                            "case": case.id,
                            "error": type(exc).__name__,
                            "delay_s": round(delay, 2),
                        }
                    },
                )
                await asyncio.sleep(delay)
                continue
            break
        score = getattr(metric, "score", None)
        duration = round((time.perf_counter() - started) * 1000, 1)
        model_name = getattr(metric, "evaluation_model", None)
        cost = getattr(metric, "evaluation_cost", None)
        if not isinstance(score, int | float) or math.isnan(score) or not 0.0 <= score <= 1.0:
            return MetricOutcome(
                status=MetricStatus.ERROR,
                error=f"Judge returned an invalid score: {score!r}",
                duration_ms=duration,
                attempts=attempts,
                evaluation_model=model_name,
                **base,
            )
        return MetricOutcome(
            status=MetricStatus.PASSED if score >= threshold else MetricStatus.FAILED,
            score=float(score),
            reason=getattr(metric, "reason", None),
            duration_ms=duration,
            attempts=attempts,
            evaluation_model=model_name,
            evaluation_cost=float(cost) if isinstance(cost, int | float) else None,
            **base,
        )

    message = redact(f"{type(last_error).__name__}: {last_error}", secrets)[:1000]
    if isinstance(last_error, TimeoutError):
        message = f"Judge did not respond within {timeout_seconds:g} seconds."
    return MetricOutcome(
        status=MetricStatus.ERROR,
        error=message,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        attempts=attempts,
        **base,
    )

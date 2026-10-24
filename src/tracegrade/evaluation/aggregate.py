"""Aggregation of per-case results into run-level statistics.

Formulas (per metric, over the cases of one run):

* ``evaluated``  = passed + failed (cases where the metric produced a score)
* ``mean_score`` = arithmetic mean of the scores of evaluated cases
* ``pass_rate``  = passed / evaluated
* errors and skips are counted separately and never contribute to either number.

Run level:

* ``case_pass_rate`` = passed cases / (passed + failed + incomplete cases); agent errors
  are excluded and reported as their own count.

TraceGrade deliberately does not combine different metrics into one weighted "overall
score": the metrics measure different things on different scales of reliability
(deterministic checks vs. judge opinions), and a single number would hide that.
"""

from __future__ import annotations

from statistics import fmean

from tracegrade.evaluation.metrics import METRICS
from tracegrade.evaluation.models import (
    CaseResult,
    CaseStatus,
    ExecutionStatus,
    MetricOutcome,
    MetricStatus,
    MetricSummary,
    RunRecord,
    RunSummary,
)


def case_status(execution_status: ExecutionStatus, outcomes: list[MetricOutcome]) -> CaseStatus:
    if execution_status is not ExecutionStatus.COMPLETED:
        return CaseStatus.ERROR
    statuses = {o.status for o in outcomes}
    if MetricStatus.FAILED in statuses:
        return CaseStatus.FAILED
    if MetricStatus.ERROR in statuses:
        return CaseStatus.INCOMPLETE
    if MetricStatus.PASSED in statuses:
        return CaseStatus.PASSED
    return CaseStatus.INCOMPLETE  # nothing could be evaluated


def summarize_metric(metric_id: str, threshold: float, cases: list[CaseResult]) -> MetricSummary:
    definition = METRICS[metric_id]
    summary = MetricSummary(
        metric_id=metric_id, name=definition.name, kind=definition.kind, threshold=threshold
    )
    scores: list[float] = []
    for case in cases:
        outcome = case.metric(metric_id)
        if outcome is None:
            continue
        if outcome.status is MetricStatus.PASSED:
            summary.passed += 1
        elif outcome.status is MetricStatus.FAILED:
            summary.failed += 1
        elif outcome.status is MetricStatus.ERROR:
            summary.errors += 1
        else:
            summary.skipped += 1
        if (
            outcome.status in (MetricStatus.PASSED, MetricStatus.FAILED)
            and outcome.score is not None
        ):
            scores.append(outcome.score)
    summary.evaluated = summary.passed + summary.failed
    if scores:
        summary.mean_score = round(fmean(scores), 4)
        summary.min_score = min(scores)
        summary.max_score = max(scores)
    return summary


def summarize_run(record: RunRecord) -> RunSummary:
    cases = record.cases
    summary = RunSummary(
        total_cases=len(record.config.case_ids),
        finished_cases=len(cases),
        passed=sum(c.status is CaseStatus.PASSED for c in cases),
        failed=sum(c.status is CaseStatus.FAILED for c in cases),
        incomplete=sum(c.status is CaseStatus.INCOMPLETE for c in cases),
        errors=sum(c.status is CaseStatus.ERROR for c in cases),
        metrics=[
            summarize_metric(mid, record.config.thresholds[mid], cases)
            for mid in record.config.metric_ids
        ],
        total_tickets=sum(len(c.execution.tickets) for c in cases),
        total_refunded=round(sum(c.execution.refunded_total for c in cases), 2),
    )
    in_tokens = [c.execution.input_tokens for c in cases if c.execution.input_tokens is not None]
    out_tokens = [c.execution.output_tokens for c in cases if c.execution.output_tokens is not None]
    summary.agent_input_tokens = sum(in_tokens) if in_tokens else None
    summary.agent_output_tokens = sum(out_tokens) if out_tokens else None
    costs = [m.evaluation_cost for c in cases for m in c.metrics if m.evaluation_cost is not None]
    summary.judge_cost = round(sum(costs), 6) if costs else None
    latencies = [c.execution.latency_ms for c in cases]
    summary.mean_agent_latency_ms = round(fmean(latencies), 1) if latencies else None
    return summary

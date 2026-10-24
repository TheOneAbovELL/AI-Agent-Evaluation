"""Metric catalogue.

``METRICS`` maps metric id -> definition for every available metric, in display order.
Suites are named selections used by the CLI (``--suite``) and the UI.
"""

from __future__ import annotations

import time
from typing import Any

from tracegrade.evaluation.dataset import EvalCase
from tracegrade.evaluation.metrics.base import MetricDefinition, MetricScore, NotApplicable
from tracegrade.evaluation.metrics.deterministic import DETERMINISTIC_METRICS, DeterministicFn
from tracegrade.evaluation.metrics.judge import JUDGE_METRIC_DEFINITIONS
from tracegrade.evaluation.models import AgentExecution, MetricOutcome, MetricStatus

METRICS: dict[str, MetricDefinition] = {
    **{mid: d for mid, (d, _) in DETERMINISTIC_METRICS.items()},
    **JUDGE_METRIC_DEFINITIONS,
}

NO_JUDGE_SUITE = [mid for mid, d in METRICS.items() if not d.requires_judge]
JUDGE_SUITE = [mid for mid, d in METRICS.items() if d.requires_judge]

SUITES: dict[str, list[str]] = {
    "deterministic": NO_JUDGE_SUITE,
    "judge": JUDGE_SUITE,
    "all": list(METRICS),
}


def resolve_metric_ids(metric_ids: list[str] | None = None, suite: str | None = None) -> list[str]:
    from tracegrade.errors import ConfigurationError

    if metric_ids:
        unknown = [m for m in metric_ids if m not in METRICS]
        if unknown:
            raise ConfigurationError(
                f"Unknown metric(s): {', '.join(unknown)}. Known: {', '.join(METRICS)}."
            )
        # keep catalogue order, drop duplicates
        return [m for m in METRICS if m in set(metric_ids)]
    suite = suite or "all"
    if suite not in SUITES:
        raise ConfigurationError(f"Unknown suite '{suite}'. Choose one of: {', '.join(SUITES)}.")
    return list(SUITES[suite])


def run_deterministic_metric(
    metric_id: str, case: EvalCase, execution: AgentExecution, threshold: float
) -> MetricOutcome:
    definition, fn = DETERMINISTIC_METRICS[metric_id]
    base: dict[str, Any] = {
        "metric_id": definition.id,
        "name": definition.name,
        "kind": definition.kind,
        "threshold": threshold,
        "evaluation_model": "none (deterministic)",
    }
    started = time.perf_counter()
    try:
        result = fn(case, execution)
    except NotApplicable as na:
        return MetricOutcome(status=MetricStatus.SKIPPED, reason=str(na), **base)
    except Exception as exc:  # a metric bug must not abort the run
        return MetricOutcome(
            status=MetricStatus.ERROR,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            **base,
        )
    return MetricOutcome(
        status=MetricStatus.PASSED if result.score >= threshold else MetricStatus.FAILED,
        score=result.score,
        reason=result.reason,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        attempts=1,
        **base,
    )


__all__ = [
    "JUDGE_SUITE",
    "METRICS",
    "NO_JUDGE_SUITE",
    "SUITES",
    "DeterministicFn",
    "MetricDefinition",
    "MetricScore",
    "NotApplicable",
    "resolve_metric_ids",
    "run_deterministic_metric",
]

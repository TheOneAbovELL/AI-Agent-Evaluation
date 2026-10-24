"""Metric definitions shared by deterministic and LLM-judge metrics."""

from __future__ import annotations

from dataclasses import dataclass, field

from tracegrade.evaluation.models import MetricKind


class NotApplicable(Exception):
    """Raised by a metric when the case lacks the evidence the metric needs."""


@dataclass(frozen=True)
class MetricScore:
    score: float
    reason: str


@dataclass(frozen=True)
class MetricDefinition:
    id: str
    name: str
    kind: MetricKind
    description: str
    default_threshold: float
    #: what the score is computed from (shown in the UI and the docs)
    evidence: str
    #: how the score is computed
    method: str
    requires_judge: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

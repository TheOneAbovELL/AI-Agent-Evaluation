"""Result data model: what one evaluation run records.

Hierarchy::

    RunRecord
      config: RunConfig          (everything needed to reproduce the run)
      environment                (package versions, platform)
      cases: [CaseResult]
        execution: AgentExecution   (answer, tool calls, tickets, trace, timing, errors)
        metrics: [MetricOutcome]    (one per selected metric)
      summary: RunSummary        (aggregates, recomputed from cases)

Status vocabularies
-------------------
MetricOutcome.status  passed | failed | error | skipped
    *skipped* = the metric does not apply to this case (missing reference data) or its
    prerequisite is unavailable (no judge configured). *error* = it applied but could not
    be computed (judge timeout, malformed judge output, agent failure). Neither counts as
    a pass or a fail, and neither contributes a score.
CaseResult.status     passed | failed | incomplete | error
    *error*: the agent itself failed; *failed*: at least one metric failed;
    *incomplete*: nothing failed but some metric errored; *passed*: every evaluated
    metric passed (at least one).
RunRecord.status      running | completed | interrupted | failed
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from tracegrade.config import PolicyMode
from tracegrade.providers.registry import ModelSpec


def utc_now() -> datetime:
    return datetime.now(UTC)


class ToolCallRecord(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    call_id: str | None = None


class TicketRecord(BaseModel):
    ticket_id: str
    customer_id: str
    amount: float


class ExecutionStatus(StrEnum):
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"


class AgentExecution(BaseModel):
    status: ExecutionStatus
    answer: str | None = None
    conversation_continues: bool | None = None
    structured_response: bool = False
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    tickets: list[TicketRecord] = Field(default_factory=list)
    rejected_tickets: list[dict[str, str]] = Field(default_factory=list)
    trace: dict[str, Any] | None = None
    latency_ms: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_type: str | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @property
    def refunded_total(self) -> float:
        return round(sum(t.amount for t in self.tickets), 2)


class MetricKind(StrEnum):
    DETERMINISTIC = "deterministic"
    HEURISTIC = "heuristic"
    LLM_JUDGE = "llm_judge"


class MetricStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class MetricOutcome(BaseModel):
    metric_id: str
    name: str
    kind: MetricKind
    status: MetricStatus
    score: float | None = None
    threshold: float
    reason: str | None = None
    error: str | None = None
    duration_ms: float = 0.0
    attempts: int = 0
    evaluation_model: str | None = None
    evaluation_cost: float | None = None


class CaseStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    ERROR = "error"


class CaseResult(BaseModel):
    case_id: str
    input: str
    expected_output: str | None = None
    expected_refund_total: float | None = None
    tags: list[str] = Field(default_factory=list)
    execution: AgentExecution
    metrics: list[MetricOutcome] = Field(default_factory=list)
    status: CaseStatus
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)

    def metric(self, metric_id: str) -> MetricOutcome | None:
        return next((m for m in self.metrics if m.metric_id == metric_id), None)


class RunConfig(BaseModel):
    dataset_name: str
    dataset_source: str
    dataset_sha256: str
    reference_date: str
    case_ids: list[str]
    agent: ModelSpec
    judge: ModelSpec | None = None
    metric_ids: list[str]
    thresholds: dict[str, float]
    policy_mode: PolicyMode
    max_concurrency: int = 1
    agent_recursion_limit: int = 25
    prompt_fingerprint: str
    label: str | None = None


class MetricSummary(BaseModel):
    metric_id: str
    name: str
    kind: MetricKind
    threshold: float
    evaluated: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    mean_score: float | None = None
    min_score: float | None = None
    max_score: float | None = None

    @property
    def pass_rate(self) -> float | None:
        return self.passed / self.evaluated if self.evaluated else None


class RunSummary(BaseModel):
    total_cases: int = 0
    finished_cases: int = 0
    passed: int = 0
    failed: int = 0
    incomplete: int = 0
    errors: int = 0
    metrics: list[MetricSummary] = Field(default_factory=list)
    total_tickets: int = 0
    total_refunded: float = 0.0
    agent_input_tokens: int | None = None
    agent_output_tokens: int | None = None
    judge_cost: float | None = None
    mean_agent_latency_ms: float | None = None

    @property
    def case_pass_rate(self) -> float | None:
        scored = self.passed + self.failed + self.incomplete
        return self.passed / scored if scored else None


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class RunRecord(BaseModel):
    schema_version: int = 1
    run_id: str
    created_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.RUNNING
    config: RunConfig
    environment: dict[str, str] = Field(default_factory=dict)
    cases: list[CaseResult] = Field(default_factory=list)
    summary: RunSummary = Field(default_factory=RunSummary)
    error: str | None = None

    @property
    def is_offline(self) -> bool:
        return self.config.agent.provider == "offline"

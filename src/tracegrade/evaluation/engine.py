"""Evaluation orchestration.

Lifecycle of a run::

    RunRequest --preflight()--> errors/warnings (nothing executed yet)
               --run()------->  RunRecord(status=running) saved
                                for each case (bounded concurrency):
                                    execute agent once           -> AgentExecution
                                    deterministic metrics        -> MetricOutcome*
                                    DeepEval metrics (concurrent)-> MetricOutcome*
                                    case status, save record     (incremental)
                                status = completed | interrupted | failed, summary, save

The agent runs exactly once per case and every metric scores that same execution, so
scores of different metrics are about the same behaviour.
"""

from __future__ import annotations

import asyncio
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from tracegrade.config import PolicyMode, Settings
from tracegrade.errors import ConfigurationError, DatasetError, TraceGradeError
from tracegrade.evaluation.aggregate import case_status, summarize_run
from tracegrade.evaluation.dataset import EvalCase, LoadedDataset, resolve_dataset
from tracegrade.evaluation.execution import execute_case
from tracegrade.evaluation.metrics import METRICS, run_deterministic_metric
from tracegrade.evaluation.metrics.deterministic import DETERMINISTIC_METRICS
from tracegrade.evaluation.metrics.judge import make_deepeval_metric, run_judge_metric
from tracegrade.evaluation.models import (
    CaseResult,
    ExecutionStatus,
    MetricOutcome,
    MetricStatus,
    RunConfig,
    RunRecord,
    RunStatus,
    utc_now,
)
from tracegrade.evaluation.storage import RunStore
from tracegrade.logging_utils import get_logger
from tracegrade.providers.registry import ModelSpec, build_chat_model, build_judge
from tracegrade.refund.prompts import prompt_fingerprint

log = get_logger("evaluation.engine")

_TRACKED_PACKAGES = (
    "tracegrade",
    "deepeval",
    "langchain",
    "langchain-core",
    "langgraph",
    "langchain-openai",
    "langchain-groq",
    "pydantic",
)


class RunRequest(BaseModel):
    dataset: LoadedDataset
    case_ids: list[str] | None = None
    agent: ModelSpec
    judge: ModelSpec | None = None
    metric_ids: list[str] = Field(min_length=1)
    thresholds: dict[str, float] = Field(default_factory=dict)
    policy_mode: PolicyMode = PolicyMode.ENFORCED
    max_concurrency: int = Field(default=1, ge=1, le=16)
    recursion_limit: int = Field(default=25, ge=5, le=200)
    label: str | None = Field(default=None, max_length=120)


@dataclass
class Preflight:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class EngineEvent:
    kind: Literal["run_started", "case_started", "case_finished", "run_finished"]
    record: RunRecord
    case_id: str | None = None
    case_result: CaseResult | None = None
    completed: int = 0
    total: int = 0


EventCallback = Callable[[EngineEvent], None]


def environment_info() -> dict[str, str]:
    info = {"python": sys.version.split()[0], "platform": platform.platform()}
    for package in _TRACKED_PACKAGES:
        try:
            info[package] = version(package)
        except PackageNotFoundError:
            info[package] = "not installed"
    return info


def new_run_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"


class EvaluationEngine:
    def __init__(
        self,
        settings: Settings,
        store: RunStore | None = None,
        *,
        chat_model_factory: Callable[[ModelSpec, Settings], Any] = build_chat_model,
        judge_factory: Callable[[ModelSpec, Settings], Any] = build_judge,
        judge_backoff_seconds: float = 1.0,
    ) -> None:
        self.settings = settings
        self.store = store
        self._chat_model_factory = chat_model_factory
        self._judge_factory = judge_factory
        self._judge_backoff = judge_backoff_seconds
        self._secrets = tuple(
            key.get_secret_value()
            for key in (settings.openai_api_key, settings.groq_api_key)
            if key is not None
        )

    # ------------------------------------------------------------------ preflight --
    def thresholds_for(self, request: RunRequest) -> dict[str, float]:
        return {
            mid: request.thresholds.get(mid, METRICS[mid].default_threshold)
            for mid in request.metric_ids
            if mid in METRICS
        }

    def preflight(self, request: RunRequest) -> Preflight:
        result = Preflight()
        dataset = request.dataset.dataset
        try:
            cases = dataset.select(request.case_ids)
        except DatasetError as exc:
            result.errors.append(str(exc))
            cases = []
        unknown = [m for m in request.metric_ids if m not in METRICS]
        if unknown:
            result.errors.append(f"Unknown metric(s): {', '.join(unknown)}.")
        for mid, value in request.thresholds.items():
            if mid not in METRICS:
                result.errors.append(f"Threshold given for unknown metric '{mid}'.")
            elif not 0.0 <= value <= 1.0:
                result.errors.append(f"Threshold for '{mid}' must be between 0 and 1.")
        try:
            self._chat_model_factory(request.agent, self.settings)
        except TraceGradeError as exc:
            result.errors.append(f"Agent model: {exc}")
        judge_metrics = [
            m for m in request.metric_ids if m in METRICS and METRICS[m].requires_judge
        ]
        if request.judge is None:
            if judge_metrics:
                result.warnings.append(
                    f"No judge model configured: {len(judge_metrics)} LLM-judge metric(s) "
                    f"({', '.join(judge_metrics)}) will be reported as skipped."
                )
        else:
            try:
                self._judge_factory(request.judge, self.settings)
            except TraceGradeError as exc:
                result.errors.append(f"Judge model: {exc}")
        result.warnings.extend(dataset.warnings())
        if request.agent.provider == "offline":
            result.info.append(
                "Agent is the offline rule-based reference model, not an LLM. Scores verify "
                "the pipeline and dataset, not model quality."
            )
        else:
            result.info.append(
                f"Real API usage: about {len(cases)} agent run(s) of several model calls each "
                f"on {request.agent.label}."
            )
        if request.judge is not None and judge_metrics:
            result.info.append(
                f"Judge usage: {len(cases)} case(s) x {len(judge_metrics)} judge metric(s) on "
                f"{request.judge.label}; each metric makes one or more judge calls."
            )
        return result

    def create_record(self, request: RunRequest) -> RunRecord:
        dataset = request.dataset.dataset
        cases = dataset.select(request.case_ids)
        config = RunConfig(
            dataset_name=dataset.name,
            dataset_source=request.dataset.source,
            dataset_sha256=request.dataset.sha256,
            reference_date=dataset.reference_date.isoformat(),
            case_ids=[c.id for c in cases],
            agent=request.agent,
            judge=request.judge,
            metric_ids=list(request.metric_ids),
            thresholds=self.thresholds_for(request),
            policy_mode=request.policy_mode,
            max_concurrency=request.max_concurrency,
            agent_recursion_limit=request.recursion_limit,
            prompt_fingerprint=prompt_fingerprint(),
            label=request.label,
        )
        return RunRecord(run_id=new_run_id(), config=config, environment=environment_info())

    # ---------------------------------------------------------------------- run --
    async def run(
        self,
        request: RunRequest,
        *,
        on_event: EventCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
        record: RunRecord | None = None,
    ) -> RunRecord:
        preflight = self.preflight(request)
        if not preflight.ok:
            raise ConfigurationError("Run cannot start:\n  " + "\n  ".join(preflight.errors))
        record = record or self.create_record(request)
        return await self._execute(request, record, on_event, should_cancel)

    async def resume(
        self,
        run_id: str,
        *,
        retry_errors: bool = False,
        on_event: EventCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> RunRecord:
        """Finish an interrupted run: evaluate the cases it does not have results for."""
        if self.store is None:
            raise ConfigurationError("Resuming needs a run store.")
        record = self.store.load(run_id)
        dataset = resolve_dataset(record.config.dataset_source, self.settings.max_upload_bytes)
        if dataset.sha256 != record.config.dataset_sha256:
            raise DatasetError(
                f"Dataset {record.config.dataset_source} changed since run {run_id} started "
                "(content hash differs); start a new run instead."
            )
        if retry_errors:
            record.cases = [c for c in record.cases if c.status.value != "error"]
        request = RunRequest(
            dataset=dataset,
            case_ids=record.config.case_ids,
            agent=record.config.agent,
            judge=record.config.judge,
            metric_ids=record.config.metric_ids,
            thresholds=record.config.thresholds,
            policy_mode=record.config.policy_mode,
            max_concurrency=record.config.max_concurrency,
            recursion_limit=record.config.agent_recursion_limit,
            label=record.config.label,
        )
        preflight = self.preflight(request)
        if not preflight.ok:
            raise ConfigurationError("Run cannot resume:\n  " + "\n  ".join(preflight.errors))
        return await self._execute(request, record, on_event, should_cancel)

    def run_sync(self, request: RunRequest, **kwargs: Any) -> RunRecord:
        return asyncio.run(self.run(request, **kwargs))

    # ---------------------------------------------------------------- internals --
    def _save(self, record: RunRecord) -> None:
        record.summary = summarize_run(record)
        if self.store is not None:
            self.store.save(record)

    async def _execute(
        self,
        request: RunRequest,
        record: RunRecord,
        on_event: EventCallback | None,
        should_cancel: Callable[[], bool] | None,
    ) -> RunRecord:
        dataset = request.dataset.dataset
        order = {cid: i for i, cid in enumerate(record.config.case_ids)}
        done_ids = {c.case_id for c in record.cases}
        pending = [c for c in dataset.select(record.config.case_ids) if c.id not in done_ids]
        total = len(record.config.case_ids)
        judge = (
            self._judge_factory(request.judge, self.settings) if request.judge is not None else None
        )
        record.status = RunStatus.RUNNING
        record.finished_at = None
        self._save(record)
        emit = on_event or (lambda _event: None)
        emit(EngineEvent("run_started", record, completed=len(record.cases), total=total))
        log.info(
            "run started",
            extra={
                "ctx": {
                    "run_id": record.run_id,
                    "cases": len(pending),
                    "agent": request.agent.label,
                    "judge": request.judge.label if request.judge else "none",
                }
            },
        )

        lock = asyncio.Lock()
        case_slots = asyncio.Semaphore(request.max_concurrency)
        judge_slots = asyncio.Semaphore(request.max_concurrency * 3)
        cancelled = False

        async def evaluate(case: EvalCase) -> None:
            nonlocal cancelled
            async with case_slots:
                if cancelled or (should_cancel is not None and should_cancel()):
                    cancelled = True
                    return
                emit(
                    EngineEvent(
                        "case_started",
                        record,
                        case_id=case.id,
                        completed=len(record.cases),
                        total=total,
                    )
                )
                result = await self._evaluate_case(case, request, record, judge, judge_slots)
                async with lock:
                    record.cases.append(result)
                    record.cases.sort(key=lambda c: order.get(c.case_id, 0))
                    self._save(record)
                emit(
                    EngineEvent(
                        "case_finished",
                        record,
                        case_id=case.id,
                        case_result=result,
                        completed=len(record.cases),
                        total=total,
                    )
                )

        try:
            await asyncio.gather(*(evaluate(c) for c in pending))
        except Exception as exc:
            record.status = RunStatus.FAILED
            record.error = f"{type(exc).__name__}: {exc}"
            record.finished_at = utc_now()
            self._save(record)
            raise
        except BaseException:
            # Ctrl+C, task cancellation, or a UI stop (Streamlit's StopException).
            record.status = RunStatus.INTERRUPTED
            record.error = "Run was interrupted; completed cases were kept. Resume it to finish."
            record.finished_at = utc_now()
            self._save(record)
            raise
        if cancelled or len(record.cases) < total:
            record.status = RunStatus.INTERRUPTED
            record.error = "Run was stopped before all cases finished; resume it to finish."
        else:
            record.status = RunStatus.COMPLETED
            record.error = None
        record.finished_at = utc_now()
        self._save(record)
        emit(EngineEvent("run_finished", record, completed=len(record.cases), total=total))
        log.info(
            "run finished",
            extra={
                "ctx": {
                    "run_id": record.run_id,
                    "status": record.status.value,
                    "passed": record.summary.passed,
                    "failed": record.summary.failed,
                    "errors": record.summary.errors,
                }
            },
        )
        return record

    async def _evaluate_case(
        self,
        case: EvalCase,
        request: RunRequest,
        record: RunRecord,
        judge: Any,
        judge_slots: asyncio.Semaphore,
    ) -> CaseResult:
        started = utc_now()
        model = self._chat_model_factory(request.agent, self.settings)
        execution = await execute_case(
            case,
            request.dataset.dataset,
            model,
            policy_mode=request.policy_mode,
            timeout_seconds=request.agent.timeout_seconds,
            recursion_limit=request.recursion_limit,
            model_retries=0 if request.agent.provider == "offline" else request.agent.max_retries,
            secrets=self._secrets,
        )
        thresholds = record.config.thresholds
        outcomes: list[MetricOutcome] = []
        judge_jobs = []
        for mid in record.config.metric_ids:
            definition = METRICS[mid]
            threshold = thresholds[mid]
            if execution.status is not ExecutionStatus.COMPLETED:
                outcomes.append(
                    MetricOutcome(
                        metric_id=mid,
                        name=definition.name,
                        kind=definition.kind,
                        status=MetricStatus.SKIPPED,
                        threshold=threshold,
                        reason=f"Not evaluated: agent execution {execution.status.value}.",
                    )
                )
                continue
            if mid in DETERMINISTIC_METRICS:
                outcomes.append(run_deterministic_metric(mid, case, execution, threshold))
                continue
            if definition.requires_judge and judge is None:
                outcomes.append(
                    MetricOutcome(
                        metric_id=mid,
                        name=definition.name,
                        kind=definition.kind,
                        status=MetricStatus.SKIPPED,
                        threshold=threshold,
                        reason="No judge model configured for this run.",
                    )
                )
                continue
            judge_jobs.append((mid, definition, threshold))

        async def measure(mid: str, definition: Any, threshold: float) -> MetricOutcome:
            async with judge_slots:
                return await run_judge_metric(
                    definition,
                    case,
                    execution,
                    metric_factory=lambda: make_deepeval_metric(mid, judge, threshold),
                    threshold=threshold,
                    timeout_seconds=(request.judge.timeout_seconds if request.judge else 120.0),
                    max_retries=(request.judge.max_retries if request.judge else 0),
                    secrets=self._secrets,
                    backoff_base=self._judge_backoff,
                )

        if judge_jobs:
            outcomes.extend(await asyncio.gather(*(measure(*job) for job in judge_jobs)))
        position = {mid: i for i, mid in enumerate(record.config.metric_ids)}
        outcomes.sort(key=lambda o: position[o.metric_id])
        return CaseResult(
            case_id=case.id,
            input=case.input,
            expected_output=case.expected_output,
            expected_refund_total=case.expected_refund_total,
            tags=list(case.tags),
            execution=execution,
            metrics=outcomes,
            status=case_status(execution.status, outcomes),
            started_at=started,
            finished_at=utc_now(),
        )

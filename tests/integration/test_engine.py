"""Engine integration: real agent graph + tools + metrics + storage (offline / fake models)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import FailingChatModel, LoopingChatModel, SlowChatModel
from tests.fakes import SchemaFillingJudge
from tracegrade.config import PolicyMode, Settings
from tracegrade.errors import ConfigurationError, DatasetError
from tracegrade.evaluation.dataset import LoadedDataset, load_dataset
from tracegrade.evaluation.engine import EngineEvent, EvaluationEngine, RunRequest
from tracegrade.evaluation.metrics import JUDGE_SUITE, NO_JUDGE_SUITE, SUITES
from tracegrade.evaluation.models import CaseStatus, ExecutionStatus, MetricStatus, RunStatus
from tracegrade.evaluation.storage import RunStore
from tracegrade.providers.registry import ModelSpec, build_chat_model

OFFLINE = ModelSpec(provider="offline", model="reference")


def request(dataset: LoadedDataset, **kw: Any) -> RunRequest:
    params: dict[str, Any] = {"dataset": dataset, "agent": OFFLINE, "metric_ids": SUITES["all"]}
    params.update(kw)
    return RunRequest(**params)


def test_offline_reference_run_passes_and_is_persisted(
    engine: EvaluationEngine, bundled: LoadedDataset, store: RunStore
) -> None:
    events: list[EngineEvent] = []
    record = engine.run_sync(request(bundled, max_concurrency=4), on_event=events.append)
    assert record.status is RunStatus.COMPLETED
    s = record.summary
    assert (s.total_cases, s.passed, s.failed, s.errors) == (16, 16, 0, 0)
    by_id = {m.metric_id: m for m in s.metrics}
    for mid in NO_JUDGE_SUITE:
        assert by_id[mid].failed == 0 and by_id[mid].errors == 0
    for mid in JUDGE_SUITE:  # no judge configured -> honestly skipped
        assert by_id[mid].skipped == 16 and by_id[mid].evaluated == 0
    assert [c.case_id for c in record.cases] == record.config.case_ids  # dataset order kept
    assert store.load(record.run_id) == record
    kinds = [e.kind for e in events]
    assert (
        kinds[0] == "run_started"
        and kinds[-1] == "run_finished"
        and kinds.count("case_finished") == 16
    )
    first = record.cases[0]
    assert first.execution.trace["children"] and first.execution.tickets[0].amount == 54


def test_naive_agent_without_guardrails_is_caught(
    engine: EvaluationEngine, bundled: LoadedDataset
) -> None:
    record = engine.run_sync(
        request(
            bundled,
            agent=ModelSpec(provider="offline", model="naive"),
            policy_mode=PolicyMode.PROMPT_ONLY,
            metric_ids=NO_JUDGE_SUITE,
        )
    )
    outcome = {m.metric_id: m for m in record.summary.metrics}["refund_outcome"]
    assert outcome.failed == 5  # every case where an ineligible item is requested
    failed = {
        c.case_id for c in record.cases if c.metric("refund_outcome").status is MetricStatus.FAILED
    }
    assert failed == {
        "outside-refund-window",
        "mixed-eligibility",
        "same-day-and-expired-items",
        "future-dated-purchase",
        "thirty-day-boundary",
    }


def test_guardrails_keep_naive_refunds_correct(
    engine: EvaluationEngine, bundled: LoadedDataset
) -> None:
    record = engine.run_sync(
        request(
            bundled,
            agent=ModelSpec(provider="offline", model="naive"),
            metric_ids=["refund_outcome", "tool_order"],
        )
    )
    summary = {m.metric_id: m for m in record.summary.metrics}
    assert summary["refund_outcome"].failed == 0  # tools refuse ineligible amounts
    assert summary["tool_order"].failed == 11  # but the skipped date check is visible


def test_judge_metrics_run_with_a_judge(
    settings: Settings, store: RunStore, bundled: LoadedDataset
) -> None:
    judge = SchemaFillingJudge(score=0.95)
    engine = EvaluationEngine(
        settings, store, judge_factory=lambda spec, s: judge, judge_backoff_seconds=0
    )
    record = engine.run_sync(
        request(
            bundled,
            case_ids=["refund-two-eligible-items", "missing-customer-id"],
            judge=ModelSpec(provider="groq", model="fake"),
        )
    )
    by_id = {m.metric_id: m for m in record.summary.metrics}
    assert by_id["task_completion"].evaluated == 2 and judge.calls > 0
    missing = record.cases[1]
    assert missing.metric("argument_correctness").status is MetricStatus.SKIPPED  # no tool calls


def test_agent_failure_is_recorded_not_raised(
    settings: Settings, store: RunStore, bundled: LoadedDataset
) -> None:
    engine = EvaluationEngine(
        settings, store, chat_model_factory=lambda spec, s: FailingChatModel()
    )
    record = engine.run_sync(
        request(bundled, case_ids=["refund-single-item"], metric_ids=NO_JUDGE_SUITE)
    )
    case = record.cases[0]
    assert record.status is RunStatus.COMPLETED and case.status is CaseStatus.ERROR
    assert (
        case.execution.status is ExecutionStatus.ERROR
        and case.execution.error_type == "PermissionError"
    )
    assert "sk-abcdef" not in (case.execution.error or "") and "REDACTED" in (
        case.execution.error or ""
    )
    assert all(m.status is MetricStatus.SKIPPED for m in case.metrics)
    assert record.summary.errors == 1 and record.summary.case_pass_rate is None


def test_agent_timeout(settings: Settings, store: RunStore, bundled: LoadedDataset) -> None:
    engine = EvaluationEngine(settings, store, chat_model_factory=lambda spec, s: SlowChatModel())
    spec = ModelSpec(provider="offline", model="reference", timeout_seconds=0.2)
    record = engine.run_sync(
        request(bundled, agent=spec, case_ids=["refund-single-item"], metric_ids=["refund_outcome"])
    )
    assert record.cases[0].execution.status is ExecutionStatus.TIMEOUT
    assert "0.2 seconds" in (record.cases[0].execution.error or "")


def test_tool_loop_hits_recursion_limit(
    settings: Settings, store: RunStore, bundled: LoadedDataset
) -> None:
    engine = EvaluationEngine(
        settings, store, chat_model_factory=lambda spec, s: LoopingChatModel()
    )
    record = engine.run_sync(
        request(
            bundled,
            case_ids=["refund-single-item"],
            metric_ids=["refund_outcome"],
            recursion_limit=8,
        )
    )
    ex = record.cases[0].execution
    assert ex.error_type == "GraphRecursionError" and "recursion limit of 8" in (ex.error or "")
    assert len(ex.tool_calls) >= 3  # partial evidence is kept


def test_preflight_reports_problems_before_running(
    engine: EvaluationEngine, bundled: LoadedDataset
) -> None:
    bad = request(
        bundled,
        case_ids=["nope"],
        metric_ids=["refund_outcome", "made_up"],
        thresholds={"refund_outcome": 1.5},
        agent=ModelSpec(provider="groq", model="m"),
        judge=ModelSpec(provider="openai", model="m"),
    )
    pf = engine.preflight(bad)
    text = "\n".join(pf.errors)
    for fragment in (
        "no case 'nope'",
        "made_up",
        "between 0 and 1",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert fragment in text
    with pytest.raises(ConfigurationError, match="Run cannot start"):
        engine.run_sync(bad)
    assert engine.store.list_runs() == []  # nothing executed or saved
    warn = engine.preflight(request(bundled))
    assert warn.ok and any("will be reported as skipped" in w for w in warn.warnings)


def test_interrupted_run_can_be_resumed(engine: EvaluationEngine, bundled: LoadedDataset) -> None:
    calls = {"n": 0}

    def cancel_after_three() -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    record = engine.run_sync(
        request(bundled, metric_ids=["refund_outcome"]), should_cancel=cancel_after_three
    )
    assert record.status is RunStatus.INTERRUPTED and len(record.cases) == 3
    assert engine.store.load(record.run_id).status is RunStatus.INTERRUPTED
    resumed = asyncio.run(engine.resume(record.run_id))
    assert resumed.status is RunStatus.COMPLETED and len(resumed.cases) == 16
    assert resumed.summary.passed == 16
    assert [c.case_id for c in resumed.cases] == resumed.config.case_ids


def test_resume_refuses_changed_dataset(
    settings: Settings, store: RunStore, bundled: LoadedDataset, tmp_path: Path
) -> None:
    path = tmp_path / "copy.json"
    payload = json.loads(json.dumps(bundled.dataset.model_dump(mode="json")))
    path.write_text(json.dumps(payload), encoding="utf-8")
    engine = EvaluationEngine(settings, store)
    record = engine.run_sync(
        request(load_dataset(path), metric_ids=["refund_outcome"]), should_cancel=lambda: True
    )
    assert record.status is RunStatus.INTERRUPTED and record.cases == []
    payload["cases"][0]["input"] = "changed"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetError, match="changed since run"):
        asyncio.run(engine.resume(record.run_id))


def test_unexpected_exception_marks_run_failed(
    settings: Settings, store: RunStore, bundled: LoadedDataset
) -> None:
    def explode(spec: ModelSpec, s: Settings) -> Any:
        if explode.calls:  # preflight builds once; the case build explodes
            raise RuntimeError("factory bug")
        explode.calls += 1
        return build_chat_model(spec, s)

    explode.calls = 0  # type: ignore[attr-defined]
    engine = EvaluationEngine(settings, store, chat_model_factory=explode)
    with pytest.raises(RuntimeError):
        engine.run_sync(
            request(bundled, case_ids=["refund-single-item"], metric_ids=["refund_outcome"])
        )
    stored = store.list_runs()[0]
    assert stored.status is RunStatus.FAILED and "factory bug" in (stored.error or "")

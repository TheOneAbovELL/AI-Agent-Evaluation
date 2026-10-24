from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from tracegrade.config import PolicyMode
from tracegrade.errors import RunNotFoundError, StorageError
from tracegrade.evaluation.aggregate import case_status, summarize_metric, summarize_run
from tracegrade.evaluation.compare import compare_runs
from tracegrade.evaluation.export import (
    export,
    loads_run,
    to_cases_csv,
    to_markdown,
    to_metrics_csv,
)
from tracegrade.evaluation.models import (
    AgentExecution,
    CaseResult,
    CaseStatus,
    ExecutionStatus,
    MetricKind,
    MetricOutcome,
    MetricStatus,
    RunConfig,
    RunRecord,
    TicketRecord,
)
from tracegrade.evaluation.storage import RunStore
from tracegrade.providers.registry import ModelSpec


def outcome(
    status: str, score: float | None = None, metric_id: str = "refund_outcome"
) -> MetricOutcome:
    return MetricOutcome(
        metric_id=metric_id,
        name=metric_id,
        kind=MetricKind.DETERMINISTIC,
        status=MetricStatus(status),
        score=score,
        threshold=1.0,
        reason="r",
    )


def make_case(
    case_id: str,
    outcomes: list[MetricOutcome],
    answer: str = "ok",
    exec_status: ExecutionStatus = ExecutionStatus.COMPLETED,
) -> CaseResult:
    ex = AgentExecution(
        status=exec_status,
        answer=answer,
        latency_ms=100,
        tickets=[TicketRecord(ticket_id="TKT-0001", customer_id="u", amount=5)],
    )
    return CaseResult(
        case_id=case_id,
        input="in",
        execution=ex,
        metrics=outcomes,
        status=case_status(exec_status, outcomes),
    )


def make_record(
    cases: list[CaseResult], run_id: str = "20260101-000000-abcdef", **cfg: object
) -> RunRecord:
    config = RunConfig(
        dataset_name="d",
        dataset_source="bundled:d",
        dataset_sha256="a" * 64,
        reference_date="2026-10-15",
        case_ids=[c.case_id for c in cases],
        agent=ModelSpec(provider="offline", model="reference"),
        metric_ids=["refund_outcome"],
        thresholds={"refund_outcome": 1.0},
        policy_mode=PolicyMode.ENFORCED,
        prompt_fingerprint="f" * 16,
    )
    config = config.model_copy(update=cfg)
    record = RunRecord(run_id=run_id, config=config, cases=cases)
    record.summary = summarize_run(record)
    return record


@pytest.mark.parametrize(
    ("exec_status", "statuses", "expected"),
    [
        (ExecutionStatus.ERROR, ["passed"], CaseStatus.ERROR),
        (ExecutionStatus.TIMEOUT, [], CaseStatus.ERROR),
        (ExecutionStatus.COMPLETED, ["passed", "failed", "error"], CaseStatus.FAILED),
        (ExecutionStatus.COMPLETED, ["passed", "error"], CaseStatus.INCOMPLETE),
        (ExecutionStatus.COMPLETED, ["passed", "skipped"], CaseStatus.PASSED),
        (ExecutionStatus.COMPLETED, ["skipped"], CaseStatus.INCOMPLETE),
    ],
)
def test_case_status(
    exec_status: ExecutionStatus, statuses: list[str], expected: CaseStatus
) -> None:
    assert case_status(exec_status, [outcome(s) for s in statuses]) is expected


def test_metric_summary_excludes_errors_and_skips_from_scores() -> None:
    cases = [
        make_case("a", [outcome("passed", 1.0)]),
        make_case("b", [outcome("failed", 0.5)]),
        make_case("c", [outcome("error")]),
        make_case("d", [outcome("skipped")]),
    ]
    s = summarize_metric("refund_outcome", 1.0, cases)
    assert (s.evaluated, s.passed, s.failed, s.errors, s.skipped) == (2, 1, 1, 1, 1)
    assert s.mean_score == 0.75 and s.pass_rate == 0.5 and s.min_score == 0.5


def test_run_summary() -> None:
    record = make_record(
        [
            make_case("a", [outcome("passed", 1.0)]),
            make_case("b", [outcome("failed", 0.0)]),
            make_case("c", [], exec_status=ExecutionStatus.ERROR),
        ]
    )
    s = record.summary
    assert (s.total_cases, s.passed, s.failed, s.errors) == (3, 1, 1, 1)
    assert s.case_pass_rate == 0.5  # errors excluded from the denominator
    assert s.total_tickets == 3 and s.total_refunded == 15


def test_store_roundtrip_atomic_and_listing(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    first = make_record([make_case("a", [outcome("passed", 1.0)])], run_id="20260101-000000-aaaaaa")
    second = make_record(
        [make_case("a", [outcome("passed", 1.0)])], run_id="20260102-000000-bbbbbb"
    )
    store.save(first)
    store.save(second)
    assert store.load(first.run_id) == first
    assert [p.name for p in (tmp_path / "runs").iterdir() if p.suffix == ".tmp"] == []
    (tmp_path / "runs" / "20260103-000000-cccccc.json").write_text("{corrupt", encoding="utf-8")
    listed = [r.run_id for r in store.list_runs()]
    assert listed == [second.run_id, first.run_id] or set(listed) == {first.run_id, second.run_id}
    with pytest.raises(StorageError):
        store.load("20260103-000000-cccccc")
    store.delete(first.run_id)
    assert not store.exists(first.run_id)
    with pytest.raises(RunNotFoundError):
        store.load(first.run_id)


@pytest.mark.parametrize("bad_id", ["../etc/passwd", "..\\x", "a/b", "", "."])
def test_run_ids_cannot_escape_store(tmp_path: Path, bad_id: str) -> None:
    with pytest.raises(RunNotFoundError, match="Invalid run id"):
        RunStore(tmp_path).load(bad_id)


def test_exports() -> None:
    evil = '=HYPERLINK("http://x")'
    record = make_record(
        [
            make_case("a", [outcome("passed", 1.0)], answer=evil),
            make_case("b", [outcome("failed", 0.0)]),
        ]
    )
    assert loads_run(export(record, "json")[0]) == record
    metric_rows = list(csv.DictReader(io.StringIO(to_metrics_csv(record))))
    assert len(metric_rows) == 2 and metric_rows[0]["metric_id"] == "refund_outcome"
    case_rows = list(csv.DictReader(io.StringIO(to_cases_csv(record))))
    assert case_rows[0]["answer"].startswith("'=")  # formula injection neutralised
    assert "score:refund_outcome" in case_rows[0]
    md = to_markdown(record)
    assert "offline rule-based reference model" in md and "| Refund outcome | deterministic |" in md
    for fmt, suffix in [
        ("json", ".json"),
        ("csv", "-metrics.csv"),
        ("cases-csv", "-cases.csv"),
        ("md", ".md"),
    ]:
        assert export(record, fmt)[1].endswith(suffix)
    with pytest.raises(ValueError):
        export(record, "xlsx")
    assert "api_key" not in json.dumps(json.loads(export(record, "json")[0]))


def test_compare_runs_flags_incompatibility_and_changes() -> None:
    base = make_record(
        [make_case("a", [outcome("passed", 1.0)]), make_case("b", [outcome("failed", 0.0)])],
        run_id="20260101-000000-aaaaaa",
    )
    cand = make_record(
        [make_case("a", [outcome("failed", 0.0)]), make_case("b", [outcome("passed", 1.0)])],
        run_id="20260102-000000-bbbbbb",
        reference_date="2026-11-01",
    )
    result = compare_runs(base, cand)
    assert any("reference dates" in w for w in result.warnings)
    assert not any("thresholds" in w for w in result.warnings)
    assert [c.case_id for c in result.regressions] == ["a"]
    assert [c.case_id for c in result.improvements] == ["b"]
    delta = result.metrics[0]
    assert delta.mean_delta == 0 and delta.pass_rate_delta == 0
    assert result.cases[0].changed_metrics == ["refund_outcome: passed -> failed"]

"""Exports: full JSON, flat CSV tables and a Markdown report.

Run records never contain credentials (``ModelSpec`` has no key field and errors are
redacted at capture time), so exports are safe to share as far as secrets go. They do
contain the dataset inputs and agent outputs.
"""

from __future__ import annotations

import csv
import io
import json

from tracegrade.evaluation.models import RunRecord


def to_json(record: RunRecord) -> str:
    return record.model_dump_json(indent=2)


def metric_rows(record: RunRecord) -> list[dict[str, object]]:
    """One row per (case, metric)."""
    rows: list[dict[str, object]] = []
    for case in record.cases:
        for m in case.metrics:
            rows.append(
                {
                    "run_id": record.run_id,
                    "case_id": case.case_id,
                    "case_status": case.status.value,
                    "metric_id": m.metric_id,
                    "metric_name": m.name,
                    "kind": m.kind.value,
                    "status": m.status.value,
                    "score": "" if m.score is None else round(m.score, 4),
                    "threshold": m.threshold,
                    "reason": (m.reason or "").replace("\n", " ").strip(),
                    "error": (m.error or "").replace("\n", " ").strip(),
                    "evaluation_model": m.evaluation_model or "",
                    "duration_ms": m.duration_ms,
                    "attempts": m.attempts,
                }
            )
    return rows


def case_rows(record: RunRecord) -> list[dict[str, object]]:
    """One row per case."""
    rows: list[dict[str, object]] = []
    for case in record.cases:
        ex = case.execution
        rows.append(
            {
                "run_id": record.run_id,
                "case_id": case.case_id,
                "status": case.status.value,
                "input": case.input,
                "answer": ex.answer or "",
                "expected_refund_total": ""
                if case.expected_refund_total is None
                else case.expected_refund_total,
                "refunded_total": ex.refunded_total,
                "tickets": len(ex.tickets),
                "tools_called": " > ".join(c.name for c in ex.tool_calls),
                "execution_status": ex.status.value,
                "latency_ms": ex.latency_ms,
                "error": ex.error or "",
                **{
                    f"score:{m.metric_id}": "" if m.score is None else round(m.score, 4)
                    for m in case.metrics
                },
            }
        )
    return rows


def _csv(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        # Neutralise spreadsheet formula injection from model output.
        writer.writerow(
            {
                k: (f"'{v}" if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v)
                for k, v in row.items()
            }
        )
    return buffer.getvalue()


def to_metrics_csv(record: RunRecord) -> str:
    return _csv(metric_rows(record))


def to_cases_csv(record: RunRecord) -> str:
    return _csv(case_rows(record))


def _fmt(value: float | None, pct: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%" if pct else f"{value:.3f}"


def to_markdown(record: RunRecord) -> str:
    cfg, s = record.config, record.summary
    lines = [
        f"# Evaluation run {record.run_id}",
        "",
        f"- Status: **{record.status.value}**" + (f" - {record.error}" if record.error else ""),
        f"- Created: {record.created_at.isoformat()}",
        f"- Dataset: `{cfg.dataset_name}` ({cfg.dataset_source}, "
        f"sha256 `{cfg.dataset_sha256[:12]}`)",
        f"- Reference date: {cfg.reference_date}",
        f"- Agent: `{cfg.agent.label}`"
        + (" (offline rule-based reference model, not an LLM)" if record.is_offline else ""),
        f"- Judge: `{cfg.judge.label}`"
        if cfg.judge
        else "- Judge: none (LLM-judge metrics skipped)",
        f"- Policy mode: {cfg.policy_mode.value}",
        f"- Prompt fingerprint: `{cfg.prompt_fingerprint}`",
        "",
        "## Cases",
        "",
        f"{s.finished_cases}/{s.total_cases} finished: {s.passed} passed, {s.failed} failed, "
        f"{s.incomplete} incomplete, {s.errors} agent errors. "
        f"Case pass rate: {_fmt(s.case_pass_rate, pct=True)}.",
        "",
        "## Metrics",
        "",
        "| Metric | Kind | Threshold | Mean score | Pass rate | Passed/Evaluated | Errors "
        "| Skipped |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for m in s.metrics:
        lines.append(
            f"| {m.name} | {m.kind.value} | {m.threshold:.2f} | {_fmt(m.mean_score)} | "
            f"{_fmt(m.pass_rate, pct=True)} | {m.passed}/{m.evaluated} | {m.errors} | {m.skipped} |"
        )
    lines += ["", "## Per-case results", ""]
    for case in record.cases:
        ex = case.execution
        lines += [
            f"### {case.case_id} - {case.status.value}",
            "",
            f"**Input:** {case.input}",
            "",
            f"**Answer:** {ex.answer or '(none)'}",
            "",
            f"**Tools:** {' > '.join(c.name for c in ex.tool_calls) or '(none)'}  ",
            f"**Refunded:** ${ex.refunded_total:.2f} in {len(ex.tickets)} ticket(s)"
            + (
                f" (expected ${case.expected_refund_total:.2f})"
                if case.expected_refund_total is not None
                else ""
            ),
            "",
        ]
        if ex.error:
            lines += [f"**Agent error:** {ex.error}", ""]
        for mo in case.metrics:
            detail = mo.reason or mo.error or ""
            score = "" if mo.score is None else f" {mo.score:.2f}"
            lines.append(f"- {mo.name}: {mo.status.value}{score} - {detail.strip()}")
        lines.append("")
    lines += [
        "---",
        "LLM-judge scores are model opinions and can vary between runs and judge models.",
    ]
    return "\n".join(lines)


def export(record: RunRecord, fmt: str) -> tuple[str, str, str]:
    """Return ``(content, filename, mime_type)`` for a format name."""
    if fmt == "json":
        return to_json(record), f"{record.run_id}.json", "application/json"
    if fmt in ("csv", "metrics-csv"):
        return to_metrics_csv(record), f"{record.run_id}-metrics.csv", "text/csv"
    if fmt == "cases-csv":
        return to_cases_csv(record), f"{record.run_id}-cases.csv", "text/csv"
    if fmt in ("md", "markdown"):
        return to_markdown(record), f"{record.run_id}.md", "text/markdown"
    raise ValueError(f"Unknown export format '{fmt}'. Use json, csv, cases-csv or md.")


def loads_run(text: str) -> RunRecord:
    return RunRecord.model_validate(json.loads(text))

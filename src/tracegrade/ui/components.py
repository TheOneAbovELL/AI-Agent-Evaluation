"""Reusable UI building blocks (tables, charts, badges, case details)."""

from __future__ import annotations

import json
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from tracegrade.evaluation.export import export
from tracegrade.evaluation.metrics import METRICS
from tracegrade.evaluation.models import CaseResult, MetricKind, RunRecord

STATUS_COLORS: dict[str, Any] = {
    "passed": "green",
    "completed": "green",
    "failed": "red",
    "error": "red",
    "timeout": "red",
    "incomplete": "orange",
    "interrupted": "orange",
    "running": "blue",
    "skipped": "gray",
}

# Colour-blind-safe status palette for charts.
STATUS_SCALE = alt.Scale(
    domain=["passed", "failed", "error", "skipped"],
    range=["#2e7d4f", "#c0392b", "#e67e22", "#b0b7c3"],
)

KIND_LABELS = {
    MetricKind.DETERMINISTIC: "Deterministic",
    MetricKind.HEURISTIC: "Heuristic",
    MetricKind.LLM_JUDGE: "LLM judge",
}


def md(text: str | None) -> str:
    """Escape untrusted text for st.markdown: '$' would otherwise start LaTeX math."""
    return (text or "").replace("\\", "\\\\").replace("$", "\\$")


def badge(status: str, label: str | None = None) -> None:
    st.badge(label or status.capitalize(), color=STATUS_COLORS.get(status, "gray"))


def fmt_pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def local_time(record: RunRecord) -> str:
    """Creation time in the machine's local timezone (records store UTC)."""
    return record.created_at.astimezone().strftime("%Y-%m-%d %H:%M")


def run_title(record: RunRecord) -> str:
    label = f" · {record.config.label}" if record.config.label else ""
    return f"{local_time(record)} · {record.config.agent.label}{label}"


def offline_notice(record: RunRecord) -> None:
    if record.is_offline:
        st.info(
            "**Offline reference model.** This run used TraceGrade's rule-based stand-in, not "
            "an LLM. Its scores show that the pipeline and dataset work; they say nothing "
            "about the quality of a real model.",
            icon=":material/smart_toy:",
        )


def runs_frame(runs: list[RunRecord]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Run": r.run_id,
                "Created": local_time(r),
                "Status": r.status.value,
                "Agent": r.config.agent.label,
                "Judge": r.config.judge.label if r.config.judge else "none",
                "Cases": r.summary.finished_cases,
                "Passed": r.summary.passed,
                "Failed": r.summary.failed,
                "Errors": r.summary.errors,
                "Case pass rate": r.summary.case_pass_rate,
                "Label": r.config.label or "",
            }
            for r in runs
        ]
    )


def runs_table(runs: list[RunRecord]) -> None:
    st.dataframe(
        runs_frame(runs),
        hide_index=True,
        width="stretch",
        column_config={
            "Case pass rate": st.column_config.ProgressColumn(
                "Case pass rate", min_value=0.0, max_value=1.0, format="percent"
            ),
        },
    )


def summary_metrics(record: RunRecord) -> None:
    s = record.summary
    cols = st.columns(5)
    cols[0].metric("Cases finished", f"{s.finished_cases}/{s.total_cases}")
    cols[1].metric("Passed", s.passed)
    cols[2].metric("Failed", s.failed)
    cols[3].metric("Incomplete / errors", f"{s.incomplete} / {s.errors}")
    cols[4].metric("Case pass rate", fmt_pct(s.case_pass_rate))
    extras = []
    if s.mean_agent_latency_ms is not None:
        extras.append(f"mean agent latency {s.mean_agent_latency_ms / 1000:.2f}s")
    if s.agent_input_tokens is not None:
        extras.append(
            f"agent tokens in/out {s.agent_input_tokens:,}/{s.agent_output_tokens or 0:,}"
        )
    if s.judge_cost is not None:
        extras.append(f"judge cost reported by DeepEval ${s.judge_cost:.4f}")
    extras.append(f"{s.total_tickets} ticket(s), ${s.total_refunded:.2f} refunded")
    st.caption(md(" · ".join(extras)))


def metric_frame(record: RunRecord) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Metric": m.name,
                "id": m.metric_id,
                "Kind": KIND_LABELS[m.kind],
                "Threshold": m.threshold,
                "Mean score": m.mean_score,
                "Pass rate": m.pass_rate,
                "Passed": m.passed,
                "Evaluated": m.evaluated,
                "Errors": m.errors,
                "Skipped": m.skipped,
            }
            for m in record.summary.metrics
        ]
    )


def metric_table(record: RunRecord) -> None:
    st.dataframe(
        metric_frame(record),
        hide_index=True,
        width="stretch",
        column_config={
            "id": None,
            "Threshold": st.column_config.NumberColumn(format="%.2f"),
            "Mean score": st.column_config.NumberColumn(format="%.2f"),
            "Pass rate": st.column_config.ProgressColumn(
                min_value=0.0, max_value=1.0, format="percent"
            ),
        },
    )


def pass_rate_chart(record: RunRecord) -> None:
    rows = []
    for m in record.summary.metrics:
        for status, count in (
            ("passed", m.passed),
            ("failed", m.failed),
            ("error", m.errors),
            ("skipped", m.skipped),
        ):
            if count:
                rows.append({"Metric": m.name, "Status": status, "Cases": count})
    if not rows:
        st.caption("No metric results yet.")
        return
    order = [m.name for m in record.summary.metrics]
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_bar()
        .encode(
            y=alt.Y(
                "Metric:N",
                sort=order,
                title=None,
                axis=alt.Axis(labelLimit=260, labelOverlap=False),
            ),
            x=alt.X("Cases:Q", stack="zero", title="Cases", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("Status:N", scale=STATUS_SCALE, legend=alt.Legend(orient="bottom")),
            order=alt.Order("Status:N"),
            tooltip=["Metric", "Status", "Cases"],
        )
    )
    st.altair_chart(chart, width="stretch", height=max(180, 34 * len(order)) + 70)


def status_grid(record: RunRecord) -> None:
    rows = []
    for case in record.cases:
        for m in case.metrics:
            rows.append(
                {
                    "Case": case.case_id,
                    "Metric": m.name,
                    "Status": m.status.value,
                    "Score": "–" if m.score is None else f"{m.score:.2f}",
                }
            )
    if not rows:
        return
    metric_order = [m.name for m in record.summary.metrics]
    case_order = [c.case_id for c in record.cases]
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_rect(stroke="white", strokeWidth=1)
        .encode(
            x=alt.X(
                "Metric:N",
                sort=metric_order,
                title=None,
                axis=alt.Axis(labelAngle=-30, labelLimit=200, labelOverlap=False, orient="top"),
            ),
            y=alt.Y(
                "Case:N",
                sort=case_order,
                title=None,
                axis=alt.Axis(labelLimit=260, labelOverlap=False),
            ),
            color=alt.Color("Status:N", scale=STATUS_SCALE, legend=alt.Legend(orient="bottom")),
            tooltip=["Case", "Metric", "Status", "Score"],
        )
    )
    st.altair_chart(chart, width="stretch", height=max(220, 26 * len(case_order)) + 160)


def case_frame(record: RunRecord) -> pd.DataFrame:
    rows = []
    for case in record.cases:
        ex = case.execution
        failed = [m.name for m in case.metrics if m.status.value == "failed"]
        rows.append(
            {
                "Case": case.case_id,
                "Status": case.status.value,
                "Refunded": ex.refunded_total,
                "Expected refund": case.expected_refund_total,
                "Tools": " → ".join(c.name for c in ex.tool_calls),
                "Failed metrics": ", ".join(failed),
                "Latency (s)": round(ex.latency_ms / 1000, 2),
                "Tags": ", ".join(case.tags),
            }
        )
    return pd.DataFrame(rows)


def render_case_detail(case: CaseResult) -> None:
    ex = case.execution
    top = st.columns([3, 1])
    with top[0]:
        st.markdown(f"**Customer message**\n\n> {md(case.input)}")
    with top[1]:
        badge(case.status.value)
        st.caption(f"Agent: {ex.status.value} · {ex.latency_ms / 1000:.2f}s")
    if ex.error:
        st.error(f"Agent error ({ex.error_type}): {ex.error}")
    for warning in ex.warnings:
        st.warning(warning)

    left, right = st.columns(2)
    with left:
        st.markdown("**Agent answer**")
        st.markdown(md(ex.answer) or "_(no answer)_")
        if ex.conversation_continues is not None:
            st.caption(
                "Agent expects a reply from the customer."
                if ex.conversation_continues
                else "Agent considers the request resolved."
            )
    with right:
        st.markdown("**Reference answer**")
        st.markdown(md(case.expected_output) or "_(none in dataset)_")
        expected = (
            "not checked"
            if case.expected_refund_total is None
            else (
                "no ticket"
                if case.expected_refund_total == 0
                else f"${case.expected_refund_total:.2f}"
            )
        )
        st.caption(md(f"Expected refund: {expected} · Actually refunded: ${ex.refunded_total:.2f}"))

    st.markdown("**Metric results**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Metric": m.name,
                    "Kind": KIND_LABELS[m.kind],
                    "Status": m.status.value,
                    "Score": m.score,
                    "Threshold": m.threshold,
                    "Explanation": (m.reason or m.error or "").strip(),
                }
                for m in case.metrics
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Score": st.column_config.NumberColumn(format="%.2f"),
            "Threshold": st.column_config.NumberColumn(format="%.2f"),
            "Explanation": st.column_config.TextColumn(width="large"),
        },
    )

    st.markdown("**Tool calls**")
    if ex.tool_calls:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "#": i + 1,
                        "Tool": c.name,
                        "Arguments": json.dumps(c.args),
                        "Output": c.output or "",
                    }
                    for i, c in enumerate(ex.tool_calls)
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("The agent made no tool calls.")
    if ex.tickets:
        st.markdown(
            "**Tickets issued:** "
            + md(", ".join(f"{t.ticket_id} (${t.amount:.2f})" for t in ex.tickets))
        )
    if ex.rejected_tickets:
        st.markdown("**Tickets rejected by guardrails:**")
        for r in ex.rejected_tickets:
            st.caption(md(f"{r.get('customer_id')} ${r.get('amount')}: {r.get('reason')}"))
    with st.expander("Execution trace (what the LLM judges see)"):
        st.json(ex.trace or {}, expanded=2)


def download_buttons(record: RunRecord) -> None:
    cols = st.columns(4)
    for col, (fmt, label) in zip(
        cols,
        [
            ("json", "Full run (JSON)"),
            ("csv", "Metric results (CSV)"),
            ("cases-csv", "Case summary (CSV)"),
            ("md", "Report (Markdown)"),
        ],
        strict=True,
    ):
        content, filename, mime = export(record, fmt)
        col.download_button(
            label,
            data=content,
            file_name=filename,
            mime=mime,
            width="stretch",
            icon=":material/download:",
            key=f"dl-{record.run_id}-{fmt}",
        )


def metric_reference_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Metric": d.name,
                "id": d.id,
                "Kind": KIND_LABELS[d.kind],
                "Needs judge": "yes" if d.requires_judge else "no",
                "Default threshold": d.default_threshold,
                "What it checks": d.description,
                "Evidence": d.evidence,
                "How it is computed": d.method,
            }
            for d in METRICS.values()
        ]
    )

"""Compare two runs: metric deltas and per-case status changes."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from tracegrade.evaluation.compare import compare_runs
from tracegrade.ui import components as ui
from tracegrade.ui import state

st.title("Compare runs")
runs = state.list_runs()
if len(runs) < 2:
    st.info("You need at least two runs to compare.", icon=":material/info:")
    st.page_link(state.EVALUATE_PAGE, label="Start an evaluation", icon=":material/play_circle:")
    st.stop()

by_id = {r.run_id: r for r in runs}
ids = list(by_id)
cols = st.columns(2)
baseline_id = cols[0].selectbox(
    "Baseline", ids, index=1, format_func=lambda rid: f"{ui.run_title(by_id[rid])} · {rid}"
)
candidate_id = cols[1].selectbox(
    "Candidate", ids, index=0, format_func=lambda rid: f"{ui.run_title(by_id[rid])} · {rid}"
)
if baseline_id == candidate_id:
    st.warning("Pick two different runs.")
    st.stop()

result = compare_runs(by_id[baseline_id], by_id[candidate_id])
for warning in result.warnings:
    st.warning(warning, icon=":material/warning:")

summary = st.columns(3)
summary[0].metric("Regressions (passed → not passed)", len(result.regressions))
summary[1].metric("Improvements (not passed → passed)", len(result.improvements))
summary[2].metric("Metrics compared", len(result.metrics))

st.markdown("##### Metric changes")
frame = pd.DataFrame(
    [
        {
            "Metric": d.name,
            "Baseline mean": d.baseline_mean,
            "Candidate mean": d.candidate_mean,
            "Mean Δ": d.mean_delta,
            "Baseline pass rate": d.baseline_pass_rate,
            "Candidate pass rate": d.candidate_pass_rate,
            "Pass rate Δ": d.pass_rate_delta,
        }
        for d in result.metrics
    ]
)
st.dataframe(
    frame,
    hide_index=True,
    width="stretch",
    column_config={
        c: st.column_config.NumberColumn(format="%.2f")
        for c in ["Baseline mean", "Candidate mean", "Mean Δ"]
    }
    | {
        c: st.column_config.NumberColumn(format="percent")
        for c in ["Baseline pass rate", "Candidate pass rate", "Pass rate Δ"]
    },
)
chart_rows = []
for d in result.metrics:
    for run_name, value in (
        ("Baseline", d.baseline_pass_rate),
        ("Candidate", d.candidate_pass_rate),
    ):
        if value is not None:
            chart_rows.append({"Metric": d.name, "Run": run_name, "Pass rate": value})
if chart_rows:
    chart = (
        alt.Chart(pd.DataFrame(chart_rows))
        .mark_bar()
        .encode(
            y=alt.Y("Metric:N", title=None, sort=[d.name for d in result.metrics]),
            yOffset="Run:N",
            x=alt.X("Pass rate:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            color=alt.Color(
                "Run:N",
                scale=alt.Scale(range=["#9aa5b1", "#2563eb"]),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=["Metric", "Run", alt.Tooltip("Pass rate:Q", format=".0%")],
        )
    )
    st.altair_chart(chart, width="stretch", height=max(200, 44 * len(result.metrics)) + 60)

st.markdown("##### Per-case changes")
case_frame = pd.DataFrame(
    [
        {
            "Case": c.case_id,
            "Baseline": c.baseline_status or "not run",
            "Candidate": c.candidate_status or "not run",
            "Changed metrics": "; ".join(c.changed_metrics),
        }
        for c in result.cases
    ]
)
only_changes = st.toggle("Only cases that changed", value=True)
if only_changes:
    case_frame = case_frame[
        (case_frame["Baseline"] != case_frame["Candidate"]) | (case_frame["Changed metrics"] != "")
    ]
if case_frame.empty:
    st.caption("No case-level differences.")
else:
    st.dataframe(case_frame, hide_index=True, width="stretch")

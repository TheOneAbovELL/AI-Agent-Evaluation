"""Run results: summary, metric breakdown, per-case inspection, exports, history."""

from __future__ import annotations

import streamlit as st

from tracegrade.errors import TraceGradeError
from tracegrade.evaluation.models import RunStatus
from tracegrade.ui import components as ui
from tracegrade.ui import state

st.title("Run results")
runs = state.list_runs()
if not runs:
    st.info("No runs yet.", icon=":material/info:")
    st.page_link(state.EVALUATE_PAGE, label="Start an evaluation", icon=":material/play_circle:")
    st.stop()

ids = [r.run_id for r in runs]
requested = st.query_params.get("run")
index = ids.index(requested) if requested in ids else 0
by_id = {r.run_id: r for r in runs}
run_id = st.selectbox(
    "Run",
    ids,
    index=index,
    format_func=lambda rid: f"{ui.run_title(by_id[rid])} · {by_id[rid].status.value} · {rid}",
)
if run_id != requested:
    st.query_params["run"] = run_id
try:
    record = state.store().load(run_id)
except TraceGradeError as exc:
    st.error(str(exc))
    st.stop()
cfg = record.config

head = st.columns([5, 1])
with head[0]:
    st.markdown(f"#### {ui.run_title(record)}")
with head[1]:
    ui.badge(record.status.value)
if record.error:
    st.warning(record.error)
if record.status is RunStatus.INTERRUPTED:
    st.caption(f"Finish it with `tracegrade resume {record.run_id}`.")
ui.offline_notice(record)

with st.expander("Run configuration", icon=":material/tune:"):
    c = st.columns(3)
    c[0].markdown(
        f"**Dataset** `{cfg.dataset_name}`  \n{cfg.dataset_source}  \nsha256 `{cfg.dataset_sha256[:16]}`"
        f"  \nreference date {cfg.reference_date}"
    )
    c[1].markdown(
        f"**Agent** `{cfg.agent.label}`  \ntemperature {cfg.agent.temperature}  \npolicy mode "
        f"`{cfg.policy_mode.value}`  \nprompt `{cfg.prompt_fingerprint}`"
    )
    c[2].markdown(
        f"**Judge** `{cfg.judge.label if cfg.judge else 'none'}`  \n{len(cfg.case_ids)} cases · "
        f"{len(cfg.metric_ids)} metrics  \nconcurrency {cfg.max_concurrency}  \ncreated "
        f"{record.created_at:%Y-%m-%d %H:%M:%S} UTC ({ui.local_time(record)} local)"
    )
    st.json(record.environment, expanded=False)

tab_summary, tab_cases, tab_export, tab_history = st.tabs(
    [
        ":material/insights: Summary",
        ":material/list: Cases",
        ":material/download: Export",
        ":material/history: History",
    ]
)

with tab_summary:
    ui.summary_metrics(record)
    st.markdown("##### Metrics")
    ui.metric_table(record)
    st.caption(
        "Mean score averages only evaluated cases; pass rate = passed / evaluated. Errors and "
        "skips are counted separately and never count as passes. Different metrics are not "
        "combined into one overall score."
    )
    st.markdown("##### Outcomes per metric")
    ui.pass_rate_chart(record)
    st.markdown("##### Case × metric")
    st.caption("Each cell is one metric on one case. Hover for the score.")
    ui.status_grid(record)

with tab_cases:
    frame = ui.case_frame(record)
    if frame.empty:
        st.info("This run has no finished cases.")
    else:
        filter_cols = st.columns([2, 3])
        status_filter = filter_cols[0].pills(
            "Show",
            ["passed", "failed", "incomplete", "error"],
            selection_mode="multi",
            default=["passed", "failed", "incomplete", "error"],
        )
        visible = frame[frame["Status"].isin(status_filter or [])]
        st.dataframe(
            visible,
            hide_index=True,
            width="stretch",
            column_config={
                "Refunded": st.column_config.NumberColumn(format="$%.2f"),
                "Expected refund": st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        st.markdown("##### Case details")
        case_ids = list(visible["Case"]) or list(frame["Case"])
        chosen = st.selectbox(
            "Case",
            case_ids,
            format_func=lambda cid: (
                f"{cid} · {record.cases[[c.case_id for c in record.cases].index(cid)].status.value}"
            ),
        )
        case = next(c for c in record.cases if c.case_id == chosen)
        with st.container(border=True):
            ui.render_case_detail(case)

with tab_export:
    st.markdown(
        "Download this run. JSON contains everything (configuration, environment, traces, "
        "every metric result); the CSV files are flat tables for spreadsheets; the Markdown "
        "report is human-readable. Exports contain dataset inputs and agent outputs but never "
        "API keys."
    )
    ui.download_buttons(record)
    st.caption(f"Stored at `{state.store().root / (record.run_id + '.json')}`.")

with tab_history:
    st.caption(
        "All stored runs, newest first. Delete runs with `tracegrade runs delete <id> --yes`."
    )
    ui.runs_table(runs)

"""Overview: what TraceGrade does, readiness, and recent activity."""

from __future__ import annotations

import streamlit as st

from tracegrade.providers.registry import provider_status
from tracegrade.ui import components as ui
from tracegrade.ui import state

cfg = state.settings()

st.title("TraceGrade")
st.markdown(
    "Evaluate a **tool-using LangChain agent** the way you would review a support colleague: "
    "did it reach the right outcome, call the right tools with the right arguments, follow "
    "the policy, and tell the customer the truth? TraceGrade runs the bundled refund-support "
    "agent over a dataset of scenarios, scores every run with **deterministic checks** and "
    "**DeepEval LLM-as-a-judge metrics**, and keeps every run for inspection and comparison."
)

runs = state.list_runs()

steps = st.columns(3)
with steps[0], st.container(border=True):
    st.markdown("**1 · Configure**")
    st.caption(
        "Works offline out of the box. Add a Groq or OpenAI key to `.env` to evaluate a real "
        "LLM agent and enable the judge metrics."
    )
    st.page_link(state.SETTINGS_PAGE, label="Settings & help", icon=":material/settings:")
with steps[1], st.container(border=True):
    st.markdown("**2 · Run an evaluation**")
    st.caption("Pick a dataset, agent model, judge and metrics, then watch cases complete live.")
    st.page_link(state.EVALUATE_PAGE, label="New evaluation", icon=":material/play_circle:")
with steps[2], st.container(border=True):
    st.markdown("**3 · Investigate**")
    st.caption(
        "Open per-case details: answer, tool calls, tickets, trace and every metric's reason."
    )
    st.page_link(state.RESULTS_PAGE, label="Run results", icon=":material/analytics:")

st.subheader("Provider status")
status_cols = st.columns(3)
for col, status in zip(status_cols, provider_status(cfg), strict=False):
    with col, st.container(border=True):
        st.markdown(f"**{status.display_name}**")
        ui.badge(
            "passed" if status.usable else "skipped", "Ready" if status.usable else "Not configured"
        )
        st.caption(status.message)
judge = (
    cfg.judge_provider if cfg.judge_provider != "none" else "none (judge metrics will be skipped)"
)
st.caption(
    f"Defaults from configuration: agent `{cfg.agent_provider}:{cfg.agent_model}` · "
    f"judge `{judge}` · "
    f"policy mode `{cfg.policy_mode.value}`. Key presence is checked locally; validity is only "
    "known after a call."
)

st.subheader("Recent runs")
if not runs:
    st.info(
        "No runs yet. Start with an offline run: it needs no API key and takes a few seconds.",
        icon=":material/info:",
    )
    st.page_link(
        state.EVALUATE_PAGE, label="Start your first evaluation", icon=":material/play_circle:"
    )
else:
    latest = runs[0]
    with st.container(border=True):
        head = st.columns([4, 1])
        head[0].markdown(f"**Latest:** {ui.run_title(latest)}")
        with head[1]:
            ui.badge(latest.status.value)
        ui.summary_metrics(latest)
        st.page_link(
            state.RESULTS_PAGE,
            label="Open latest run",
            icon=":material/arrow_forward:",
            query_params={"run": latest.run_id},
        )
    ui.runs_table(runs[:10])
    if len(runs) > 10:
        st.caption(f"Showing 10 of {len(runs)} runs. All runs are listed on the Run results page.")

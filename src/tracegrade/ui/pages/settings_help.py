"""Settings & help: configuration status, provider checks, metric reference, troubleshooting."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from tracegrade.config import get_settings
from tracegrade.evaluation.engine import environment_info
from tracegrade.providers.registry import (
    PROVIDERS,
    check_connection,
    default_agent_spec,
    default_judge_spec,
    provider_status,
)
from tracegrade.ui import components as ui
from tracegrade.ui import state

cfg = state.settings()
st.title("Settings & help")

tab_config, tab_metrics, tab_trouble, tab_about = st.tabs(
    ["Configuration", "Metric reference", "Troubleshooting", "About"]
)

with tab_config:
    st.markdown(
        "TraceGrade reads settings from environment variables and from a `.env` file in the "
        "directory where it was started. API keys are never shown, logged or stored in runs. "
        "Edit `.env` (copy `.env.example`) and press **Reload configuration**."
    )
    if st.button("Reload configuration", icon=":material/refresh:"):
        get_settings.cache_clear()
        st.rerun()
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Provider": s.display_name,
                    "Package": "installed" if s.package_installed else "missing",
                    "Credential": (
                        "not needed"
                        if PROVIDERS[s.name].api_key_env is None
                        else ("present" if s.credential_present else "missing")
                    ),
                    "Status": "ready" if s.usable else "not configured",
                    "Detail": s.message,
                }
                for s in provider_status(cfg)
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    agent = default_agent_spec(cfg)
    judge = default_judge_spec(cfg)
    rows = [
        ("TRACEGRADE_AGENT_PROVIDER", cfg.agent_provider),
        ("TRACEGRADE_AGENT_MODEL", cfg.agent_model),
        ("TRACEGRADE_AGENT_TEMPERATURE", cfg.agent_temperature),
        ("TRACEGRADE_AGENT_TIMEOUT_SECONDS", cfg.agent_timeout_seconds),
        ("TRACEGRADE_AGENT_MAX_RETRIES", cfg.agent_max_retries),
        ("TRACEGRADE_AGENT_RECURSION_LIMIT", cfg.agent_recursion_limit),
        ("TRACEGRADE_POLICY_MODE", cfg.policy_mode.value),
        ("TRACEGRADE_JUDGE_PROVIDER", cfg.judge_provider),
        ("TRACEGRADE_JUDGE_MODEL", cfg.judge_model),
        ("TRACEGRADE_JUDGE_TIMEOUT_SECONDS", cfg.judge_timeout_seconds),
        ("TRACEGRADE_JUDGE_MAX_RETRIES", cfg.judge_max_retries),
        ("TRACEGRADE_MAX_CONCURRENCY", cfg.max_concurrency),
        ("TRACEGRADE_RUNS_DIR", str(cfg.runs_dir.resolve())),
        ("TRACEGRADE_DATASETS_DIR", str(cfg.datasets_dir.resolve())),
        ("TRACEGRADE_MAX_UPLOAD_BYTES", cfg.max_upload_bytes),
        ("TRACEGRADE_LOG_LEVEL", cfg.log_level),
        ("OPENAI_API_KEY", "set" if cfg.openai_api_key else "not set"),
        ("GROQ_API_KEY", "set" if cfg.groq_api_key else "not set"),
    ]
    st.markdown("##### Effective configuration")
    st.dataframe(
        pd.DataFrame(rows, columns=["Variable", "Value"]).astype(str),
        hide_index=True,
        width="stretch",
    )

    st.markdown("##### Connection test")
    st.caption(
        "Makes one tiny real request to each configured model (may incur a negligible cost). "
        "Only runs when you press the button."
    )
    specs = [agent] + ([judge] if judge else [])
    if st.button("Test configured models", icon=":material/network_check:"):
        for spec in specs:
            try:
                st.success(check_connection(spec, cfg))
            except Exception as exc:
                st.error(f"{spec.label}: {type(exc).__name__}: {str(exc)[:300]}")

with tab_metrics:
    st.markdown(
        "Every metric yields a score in [0, 1] per case; a case **passes** a metric when "
        "score ≥ threshold. **Skipped** means the metric did not apply (missing reference data "
        "or no judge); **error** means it applied but could not be computed. Neither counts as "
        "pass or fail."
    )
    st.dataframe(
        ui.metric_reference_frame(),
        hide_index=True,
        width="stretch",
        column_config={
            "id": st.column_config.TextColumn("id"),
            "Default threshold": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.markdown(
        """
**Reading the results**

* **Deterministic** metrics check recorded facts (tickets in the tool ledger, tool calls and
  arguments) against the dataset. They are exact and repeatable — use them as gates.
* **Heuristic** metrics use text patterns; they can misfire on unusual phrasing.
* **LLM-judge** metrics are opinions of the judge model. They vary between runs and judge
  models and can be biased (e.g. towards longer answers or towards outputs from the same
  model family). Always read the reason before acting on a score.
* Average score and pass rate answer different questions: a metric can average 0.85 while
  passing only half the cases at threshold 0.9.
"""
    )

with tab_trouble:
    problems = {
        "“OPENAI_API_KEY is not set” / “GROQ_API_KEY is not set”": "Copy `.env.example` to `.env`, fill in the key, then press Reload configuration "
        "(or restart). Run `tracegrade doctor` in a terminal to check.",
        "Authentication error (401) during a run": "The key is present but invalid or revoked. Cases show an agent error with the "
        "provider's message. Replace the key and rerun.",
        "Rate limit (429) or timeouts": "Lower *Parallel cases*, raise timeouts, or retry later. Model clients retry "
        "transient errors; judge metrics retry with exponential backoff.",
        "“model … does not support tools” or the agent never calls tools": "Choose a model with tool-calling support (for Groq e.g. `qwen/qwen3.8-27b`).",
        "All LLM-judge metrics are “skipped”": "No judge is configured for the run. Select a judge provider on the New evaluation page.",
        "Judge metric “error: invalid JSON”": "The judge model returned malformed output. Use a stronger judge model; the case is "
        "reported as incomplete rather than scored.",
        "Dates look wrong / refunds unexpectedly refused": "The agent's “today” is the dataset's reference date, not your computer's date. "
        "Check the reference date on the Datasets page.",
        "A run shows “interrupted”": "The run stopped early (browser stop, Ctrl+C). Completed cases were saved. Finish "
        "it with `tracegrade resume <run_id>`.",
    }
    for title, body in problems.items():
        with st.expander(title):
            st.markdown(body)

with tab_about:
    st.markdown(
        "TraceGrade evaluates a LangChain `create_agent` refund-support agent with "
        "deterministic checks and DeepEval metrics. Runs are stored as JSON files in the runs "
        "directory. Data sent to providers: the dataset's customer messages and purchase records "
        "(to the agent model) and execution traces (to the judge model)."
    )
    st.json(environment_info())

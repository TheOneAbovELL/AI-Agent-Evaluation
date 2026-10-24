"""New evaluation: configure, validate, run with live progress."""

from __future__ import annotations

import asyncio
from typing import Literal

import pandas as pd
import streamlit as st

from tracegrade.config import PolicyMode
from tracegrade.errors import TraceGradeError
from tracegrade.evaluation.engine import EngineEvent, EvaluationEngine, RunRequest
from tracegrade.evaluation.metrics import METRICS
from tracegrade.evaluation.models import MetricKind
from tracegrade.providers.offline import OFFLINE_VARIANTS
from tracegrade.providers.registry import PROVIDERS, ModelSpec, provider_status
from tracegrade.ui import components as ui
from tracegrade.ui import state

cfg = state.settings()
statuses = {s.name: s for s in provider_status(cfg)}

st.title("New evaluation")
st.caption(
    "Every case runs the agent once; all selected metrics score that same execution. "
    "Nothing is executed until you press **Run evaluation**."
)

# ---------------------------------------------------------------- 1. dataset --
st.subheader("1 · Dataset")
options = state.dataset_options()
with st.expander("Upload a dataset (JSON)", icon=":material/upload_file:"):
    st.caption(
        f"Same schema as the bundled dataset (see the Datasets page). Max "
        f"{cfg.max_upload_bytes // 1000:,} KB. Valid uploads are saved to `{cfg.datasets_dir}`."
    )
    upload = st.file_uploader("Dataset file", type=["json"], label_visibility="collapsed")
    if upload is not None:
        try:
            path, loaded_upload = state.save_uploaded_dataset(upload.name, upload.getvalue())
        except TraceGradeError as exc:
            st.error(str(exc))
        else:
            st.success(
                f"Saved as `{path.name}` with {len(loaded_upload.dataset.cases)} cases. "
                "Select it below."
            )
            options = state.dataset_options()

dataset_label = st.selectbox("Dataset", list(options), key="eval_dataset")
try:
    loaded = state.load_dataset(options[dataset_label])
except TraceGradeError as exc:
    st.error(str(exc))
    st.stop()
dataset = loaded.dataset
st.caption(
    f"**{dataset.name}** · {len(dataset.cases)} cases · {len(dataset.customers)} customers · "
    f'reference date ("today" for the agent) **{dataset.reference_date}** · '
    f"sha256 `{loaded.sha256[:12]}`"
)
all_ids = [c.id for c in dataset.cases]
picked = st.multiselect(
    "Cases (empty = all)",
    all_ids,
    key=f"eval_cases_{loaded.sha256[:8]}",
    placeholder=f"All {len(all_ids)} cases",
)

# ------------------------------------------------------------------ 2. agent --
st.subheader("2 · Agent under test")
a_cols = st.columns([1, 1, 1])
provider_names = list(PROVIDERS)
default_provider = cfg.agent_provider if cfg.agent_provider in provider_names else "offline"
agent_provider = a_cols[0].selectbox(
    "Provider",
    provider_names,
    index=provider_names.index(default_provider),
    format_func=lambda p: PROVIDERS[p].display_name,
    key="eval_agent_provider",
)
if agent_provider == "offline":
    default_variant = cfg.agent_model if cfg.agent_model in OFFLINE_VARIANTS else "reference"
    agent_model = a_cols[1].selectbox(
        "Variant",
        OFFLINE_VARIANTS,
        index=OFFLINE_VARIANTS.index(default_variant),
        help="reference follows the policy; naive skips the purchase-date check.",
    )
else:
    default_model = (
        cfg.agent_model
        if cfg.agent_provider == agent_provider
        else PROVIDERS[agent_provider].default_agent_model
    )
    agent_model = a_cols[1].text_input(
        "Model", value=default_model, key=f"agent_model_{agent_provider}"
    )
policy_mode = a_cols[2].selectbox(
    "Policy mode",
    [m.value for m in PolicyMode],
    index=[m.value for m in PolicyMode].index(cfg.policy_mode.value),
    help="enforced: tools validate eligibility and ticket amounts (guardrails). "
    "prompt_only: tools only look up and sum prices; the policy lives in the prompt.",
)
if not statuses[agent_provider].usable:
    st.warning(statuses[agent_provider].message, icon=":material/key_off:")
elif agent_provider == "offline":
    st.info(
        "The offline model is a deterministic rule-based stand-in, not an LLM. Use it to check "
        "the pipeline; use a real provider to evaluate model behaviour.",
        icon=":material/smart_toy:",
    )
with st.expander("Advanced agent settings"):
    adv = st.columns(4)
    temperature = adv[0].number_input(
        "Temperature",
        0.0,
        2.0,
        float(cfg.agent_temperature or 0.0),
        0.1,
        disabled=agent_provider == "offline",
    )
    timeout = adv[1].number_input(
        "Timeout per case (s)", 5.0, 3600.0, float(cfg.agent_timeout_seconds), 5.0
    )
    retries = adv[2].number_input("Client retries", 0, 10, cfg.agent_max_retries)
    recursion = adv[3].number_input("Max graph steps", 5, 200, cfg.agent_recursion_limit)

# ------------------------------------------------------------------ 3. judge --
st.subheader("3 · LLM judge")
j_cols = st.columns([1, 1, 1])
judge_choices = ["none"] + [p for p, info in PROVIDERS.items() if info.supports_judge]
judge_default = cfg.judge_provider if cfg.judge_provider in judge_choices else "none"
judge_provider = j_cols[0].selectbox(
    "Judge provider",
    judge_choices,
    index=judge_choices.index(judge_default),
    format_func=lambda p: "None (skip judge metrics)" if p == "none" else PROVIDERS[p].display_name,
)
judge_spec: ModelSpec | None = None
if judge_provider != "none":
    default_judge_model = (
        cfg.judge_model
        if cfg.judge_provider == judge_provider
        else PROVIDERS[judge_provider].default_judge_model or ""
    )
    judge_model = j_cols[1].text_input(
        "Judge model", value=default_judge_model, key=f"judge_model_{judge_provider}"
    )
    judge_timeout = j_cols[2].number_input(
        "Judge timeout (s)", 5.0, 3600.0, float(cfg.judge_timeout_seconds), 5.0
    )
    judge_spec = ModelSpec(
        provider=judge_provider,
        model=judge_model.strip() or "unset",
        temperature=0.0,
        timeout_seconds=judge_timeout,
        max_retries=cfg.judge_max_retries,
    )
    if not statuses[judge_provider].usable:
        st.warning(statuses[judge_provider].message, icon=":material/key_off:")
    st.caption(
        "Judge scores are model opinions. They vary between runs and judge models and should be "
        "read together with their reasons."
    )

# ---------------------------------------------------------------- 4. metrics --
st.subheader("4 · Metrics")
no_judge = [m for m, d in METRICS.items() if not d.requires_judge]
judge_ids = [m for m, d in METRICS.items() if d.requires_judge]
m_cols = st.columns(2)
chosen_det = m_cols[0].multiselect(
    "Deterministic and heuristic (no LLM, free)",
    no_judge,
    default=no_judge,
    format_func=lambda m: METRICS[m].name,
)
chosen_judge = m_cols[1].multiselect(
    "LLM-judge metrics (DeepEval)",
    judge_ids,
    default=judge_ids if judge_spec is not None else [],
    format_func=lambda m: METRICS[m].name,
    help="Without a judge these are reported as skipped.",
    key=f"judge_metrics_{judge_spec is not None}",
)
metric_ids = [m for m in METRICS if m in set(chosen_det) | set(chosen_judge)]
thresholds: dict[str, float] = {}
if metric_ids:
    with st.expander("Thresholds (a case passes a metric when score ≥ threshold)"):
        edited = st.data_editor(
            pd.DataFrame(
                [
                    {
                        "id": m,
                        "Metric": METRICS[m].name,
                        "Kind": ui.KIND_LABELS[METRICS[m].kind],
                        "Threshold": METRICS[m].default_threshold,
                    }
                    for m in metric_ids
                ]
            ),
            hide_index=True,
            width="stretch",
            disabled=["id", "Metric", "Kind"],
            column_config={
                "id": None,
                "Threshold": st.column_config.NumberColumn(
                    min_value=0.0, max_value=1.0, step=0.05, format="%.2f"
                ),
            },
            key=f"thresholds_{'-'.join(metric_ids)}",
        )
        thresholds = {row["id"]: float(row["Threshold"]) for _, row in edited.iterrows()}

# -------------------------------------------------------------------- 5. run --
st.subheader("5 · Run")
r_cols = st.columns([2, 1])
label = r_cols[0].text_input(
    "Label (optional)", max_chars=120, placeholder="e.g. groq gpt-oss baseline"
)
concurrency = r_cols[1].slider("Parallel cases", 1, 8, cfg.max_concurrency)

errors: list[str] = []
request: RunRequest | None = None
if not metric_ids:
    errors.append("Select at least one metric.")
if agent_provider != "offline" and not agent_model.strip():
    errors.append("Enter an agent model name.")
if not errors:
    request = RunRequest(
        dataset=loaded,
        case_ids=picked or None,
        agent=ModelSpec(
            provider=agent_provider,
            model=agent_model.strip(),
            temperature=None if agent_provider == "offline" else temperature,
            timeout_seconds=timeout,
            max_retries=int(retries),
        ),
        judge=judge_spec,
        metric_ids=metric_ids,
        thresholds=thresholds,
        policy_mode=PolicyMode(policy_mode),
        max_concurrency=concurrency,
        recursion_limit=int(recursion),
        label=label.strip() or None,
    )
engine = EvaluationEngine(cfg, state.store())
if request is not None:
    preflight = engine.preflight(request)
    errors.extend(preflight.errors)
    for line in preflight.info:
        st.caption(f":material/info: {line}")
    for line in preflight.warnings:
        st.warning(line, icon=":material/warning:")
for line in errors:
    st.error(line, icon=":material/error:")

if st.button(
    "Run evaluation",
    type="primary",
    icon=":material/play_arrow:",
    disabled=bool(errors) or request is None,
):
    if request is None:  # the button is disabled in this state; guard anyway
        st.stop()
        raise RuntimeError("unreachable")
    total = len(dataset.select(request.case_ids))
    progress = st.progress(0.0, text=f"Starting {total} case(s)…")
    with st.status("Running evaluation…", expanded=True) as status_box:

        def on_event(event: EngineEvent) -> None:
            if event.kind == "run_started":
                st.write(f"Run `{event.record.run_id}` started.")
            elif event.kind == "case_finished" and event.case_result is not None:
                r = event.case_result
                failed = [m.name for m in r.metrics if m.status.value == "failed"]
                icon = {"passed": "✅", "failed": "❌", "incomplete": "⚠️", "error": "🛑"}[
                    r.status.value
                ]
                detail = f" — failed: {', '.join(failed)}" if failed else ""
                if r.execution.error:
                    detail = f" — agent error: {r.execution.error[:160]}"
                st.write(f"{icon} `{r.case_id}` {r.status.value}{detail}")
                progress.progress(
                    event.completed / max(event.total, 1),
                    text=f"{event.completed}/{event.total} cases",
                )

        try:
            record = asyncio.run(engine.run(request, on_event=on_event))
        except TraceGradeError as exc:
            status_box.update(label="Run could not start", state="error")
            st.error(str(exc))
            st.stop()
        except Exception as exc:
            status_box.update(label="Run failed", state="error")
            st.exception(exc)
            st.stop()
        state_name: Literal["complete", "error"] = (
            "complete" if record.status.value == "completed" else "error"
        )
        status_box.update(label=f"Run {record.status.value}", state=state_name, expanded=False)
    st.success(
        f"Run `{record.run_id}` {record.status.value}: {record.summary.passed} passed, "
        f"{record.summary.failed} failed, {record.summary.incomplete} incomplete, "
        f"{record.summary.errors} agent errors.",
        icon=":material/task_alt:",
    )
    st.page_link(
        state.RESULTS_PAGE,
        label="Open results",
        icon=":material/analytics:",
        query_params={"run": record.run_id},
    )

kinds = {METRICS[m].kind for m in metric_ids}
if MetricKind.LLM_JUDGE in kinds and judge_spec is None:
    st.caption("Tip: configure a judge provider to compute the LLM-judge metrics.")

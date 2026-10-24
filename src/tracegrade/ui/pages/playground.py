"""Agent playground: multi-turn chat with the refund agent, showing its tool calls."""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import uuid4

import streamlit as st
from langgraph.checkpoint.memory import InMemorySaver

from tracegrade.config import PolicyMode
from tracegrade.errors import TraceGradeError
from tracegrade.evaluation.execution import extract_tool_calls
from tracegrade.logging_utils import redact
from tracegrade.providers.offline import OFFLINE_VARIANTS
from tracegrade.providers.registry import PROVIDERS, ModelSpec, build_chat_model, provider_status
from tracegrade.refund.agent import build_refund_agent
from tracegrade.refund.tools import RefundToolContext
from tracegrade.ui import components as ui
from tracegrade.ui import state

cfg = state.settings()
statuses = {s.name: s for s in provider_status(cfg)}

st.title("Agent playground")
st.caption(
    "Talk to the refund agent directly. Each turn shows the tools it called. Conversations "
    "here are not stored and are not evaluations."
)

with st.sidebar:
    st.markdown("**Playground settings**")
    options = state.dataset_options()
    ds_label = st.selectbox("Customer data from", list(options))
    provider = st.selectbox(
        "Provider",
        list(PROVIDERS),
        format_func=lambda p: PROVIDERS[p].display_name,
        index=list(PROVIDERS).index(cfg.agent_provider) if cfg.agent_provider in PROVIDERS else 0,
    )
    if provider == "offline":
        model = st.selectbox("Variant", OFFLINE_VARIANTS)
    else:
        model = st.text_input(
            "Model",
            value=cfg.agent_model
            if cfg.agent_provider == provider
            else PROVIDERS[provider].default_agent_model,
        )
    policy = st.selectbox("Policy mode", [m.value for m in PolicyMode])
    real_date = st.toggle(
        "Use today's real date",
        value=False,
        help="Off: the dataset's reference date is 'today' (reproducible).",
    )
    reset = st.button("New conversation", icon=":material/restart_alt:", width="stretch")

try:
    loaded = state.load_dataset(options[ds_label])
except TraceGradeError as exc:
    st.error(str(exc))
    st.stop()
today = date.today() if real_date else loaded.dataset.reference_date
session_key = (options[ds_label], loaded.sha256, provider, model, policy, today.isoformat())

if not statuses[provider].usable:
    st.warning(statuses[provider].message, icon=":material/key_off:")
    st.stop()


def _new_session() -> dict[str, Any]:
    context = RefundToolContext(
        records=loaded.dataset.records(),
        reference_date=today,
        policy_mode=PolicyMode(policy),
        window_days=loaded.dataset.refund_window_days,
    )
    spec = ModelSpec(
        provider=provider,
        model=model.strip(),
        temperature=None if provider == "offline" else 0.0,
        timeout_seconds=cfg.agent_timeout_seconds,
        max_retries=cfg.agent_max_retries,
    )
    agent = build_refund_agent(
        build_chat_model(spec, cfg),
        context,
        checkpointer=InMemorySaver(),
        model_retries=0 if provider == "offline" else cfg.agent_max_retries,
    )
    return {
        "key": session_key,
        "agent": agent,
        "context": context,
        "thread": f"playground-{uuid4().hex}",
        "turns": [],
        "calls_seen": 0,
    }


session = st.session_state.get("playground")
if reset or session is None or session["key"] != session_key:
    try:
        session = _new_session()
    except TraceGradeError as exc:
        st.error(str(exc))
        st.stop()
    st.session_state["playground"] = session

customers = loaded.dataset.records().customer_ids()
st.caption(
    f"Agent `{provider}:{model}` · today = **{today}** · policy `{policy}` · sample customers: "
    + ", ".join(f"`{u}`" for u in customers[:6])
    + (" …" if len(customers) > 6 else "")
)
with st.expander("Customer purchase records"):
    st.json(loaded.dataset.records().to_jsonable(), expanded=1)

for turn in session["turns"]:
    with st.chat_message("user"):
        st.markdown(ui.md(turn["user"]))
    with st.chat_message("assistant", avatar=":material/support_agent:"):
        st.markdown(ui.md(turn["answer"]))
        if turn["calls"]:
            with st.expander(f"{len(turn['calls'])} tool call(s)"):
                for call in turn["calls"]:
                    st.markdown(f"`{call['name']}({json.dumps(call['args'])})`")
                    st.code(call["output"] or "", language="json")
        if turn.get("resolved"):
            st.caption("The agent considers this request resolved.")

tickets = session["context"].ledger.tickets
if tickets:
    st.success(
        ui.md(
            "Tickets issued this conversation: "
            + ", ".join(f"{t.ticket_id} {t.customer_id} ${t.amount:.2f}" for t in tickets)
        ),
        icon=":material/receipt_long:",
    )

prompt = st.chat_input(
    "Write as the customer, e.g. “I'm C1004. Please refund only the screen protector.”"
)
if prompt:
    try:
        with st.spinner("Agent is working…"):
            result = session["agent"].invoke(
                {"messages": [{"role": "user", "content": prompt[:4000]}]},
                config={
                    "configurable": {"thread_id": session["thread"]},
                    "recursion_limit": cfg.agent_recursion_limit,
                },
            )
    except Exception as exc:
        secrets = [k.get_secret_value() for k in (cfg.openai_api_key, cfg.groq_api_key) if k]
        st.error(f"The agent failed: {type(exc).__name__}: {redact(str(exc), secrets)[:500]}")
        st.stop()
    calls = extract_tool_calls(result["messages"])
    new_calls = calls[session["calls_seen"] :]
    session["calls_seen"] = len(calls)
    answer = result.get("structured_response")
    session["turns"].append(
        {
            "user": prompt,
            "answer": answer.message if answer is not None else str(result["messages"][-1].content),
            "resolved": answer is not None and not answer.awaiting_customer,
            "calls": [c.model_dump() for c in new_calls],
        }
    )
    st.rerun()

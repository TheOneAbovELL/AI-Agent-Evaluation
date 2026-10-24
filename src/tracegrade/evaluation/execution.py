"""Run the agent once for one evaluation case and capture everything metrics need.

Each case gets a brand-new agent, tool context and ledger, so cases can never leak state
(tickets, quotes, conversation memory) into each other and may run concurrently.

The agent run is *not* retried as a whole: tool calls have side effects (tickets), so a
blind retry could double-issue refunds. Transient provider errors are retried inside the
chat model client (``max_retries``), before any tool side effect of that step happens.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from tracegrade.config import PolicyMode
from tracegrade.evaluation.dataset import EvalCase, EvalDataset
from tracegrade.evaluation.models import (
    AgentExecution,
    ExecutionStatus,
    TicketRecord,
    ToolCallRecord,
)
from tracegrade.evaluation.tracing import TraceRecorder, content_text
from tracegrade.logging_utils import get_logger, redact
from tracegrade.refund.agent import build_refund_agent
from tracegrade.refund.schemas import RESPONSE_TOOL_NAME, AgentReply
from tracegrade.refund.tools import TOOL_NAMES, RefundToolContext

log = get_logger("evaluation.execution")


def extract_tool_calls(messages: list[BaseMessage]) -> list[ToolCallRecord]:
    """Tool calls in order, paired with their outputs; the response tool is excluded."""
    outputs: dict[str, str] = {}
    for m in messages:
        if isinstance(m, ToolMessage) and m.tool_call_id:
            outputs[m.tool_call_id] = content_text(m.content)
    calls: list[ToolCallRecord] = []
    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        for tc in m.tool_calls or []:
            if tc["name"] == RESPONSE_TOOL_NAME:
                continue
            call_id = tc.get("id")
            calls.append(
                ToolCallRecord(
                    name=tc["name"],
                    args=dict(tc.get("args") or {}),
                    output=outputs.get(call_id) if call_id else None,
                    call_id=call_id,
                )
            )
    return calls


def _last_ai_text(messages: list[BaseMessage]) -> str | None:
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            text = content_text(m.content).strip()
            if text:
                return text
    return None


async def execute_case(
    case: EvalCase,
    dataset: EvalDataset,
    model: BaseChatModel,
    *,
    policy_mode: PolicyMode,
    timeout_seconds: float,
    recursion_limit: int = 25,
    model_retries: int = 0,
    secrets: tuple[str, ...] = (),
) -> AgentExecution:
    context = RefundToolContext(
        records=dataset.records(),
        reference_date=dataset.reference_date,
        policy_mode=policy_mode,
        window_days=dataset.refund_window_days,
    )
    agent = build_refund_agent(model, context, model_retries=model_retries)
    recorder = TraceRecorder(available_tools=list(TOOL_NAMES))
    config: dict[str, Any] = {
        "callbacks": [recorder],
        "recursion_limit": recursion_limit,
        "configurable": {"thread_id": f"eval-{case.id}-{uuid4().hex[:8]}"},
    }
    started = time.perf_counter()
    result: dict[str, Any] | None = None
    status = ExecutionStatus.COMPLETED
    error_type: str | None = None
    error: str | None = None
    try:
        result = await asyncio.wait_for(
            agent.ainvoke({"messages": [{"role": "user", "content": case.input}]}, config=config),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        status, error_type = ExecutionStatus.TIMEOUT, "TimeoutError"
        error = f"Agent did not finish within {timeout_seconds:g} seconds."
    except GraphRecursionError:
        status, error_type = ExecutionStatus.ERROR, "GraphRecursionError"
        error = (
            f"Agent exceeded the recursion limit of {recursion_limit} steps "
            "(possible tool-calling loop)."
        )
    except Exception as exc:  # provider/auth/validation errors are reported, not raised
        status, error_type = ExecutionStatus.ERROR, type(exc).__name__
        error = redact(str(exc), secrets)[:2000] or type(exc).__name__
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    messages: list[BaseMessage] = list((result or {}).get("messages", []))
    structured = (result or {}).get("structured_response")
    warnings: list[str] = []
    answer: str | None = None
    conversation: bool | None = None
    if isinstance(structured, AgentReply):
        answer, conversation = structured.message, structured.awaiting_customer
    elif result is not None:
        answer = _last_ai_text(messages)
        warnings.append("Agent returned no structured reply; using the last AI message text.")

    tool_calls = extract_tool_calls(messages)
    if result is None:
        # The graph raised, so there is no message list; keep what the trace recorded.
        tool_calls = [
            ToolCallRecord(
                name=str(span["name"]),
                args=span["input"] if isinstance(span.get("input"), dict) else {},
                output=span.get("output") or span.get("error"),
            )
            for span in recorder.tool_spans()
        ]
        if tool_calls:
            warnings.append("Tool calls were reconstructed from the trace of a failed run.")

    if error:
        log.warning(
            "agent execution failed",
            extra={"ctx": {"case": case.id, "status": status.value, "error_type": error_type}},
        )

    return AgentExecution(
        status=status,
        answer=answer,
        conversation_continues=conversation,
        structured_response=isinstance(structured, AgentReply),
        tool_calls=tool_calls,
        tickets=[
            TicketRecord(ticket_id=t.ticket_id, customer_id=t.customer_id, amount=float(t.amount))
            for t in context.ledger.tickets
        ],
        rejected_tickets=list(context.ledger.rejected_tickets),
        trace=recorder.build(case.input, answer),
        latency_ms=latency_ms,
        input_tokens=recorder.input_tokens,
        output_tokens=recorder.output_tokens,
        error_type=error_type,
        error=error,
        warnings=warnings,
    )

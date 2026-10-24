"""Execution-trace capture.

``TraceRecorder`` is a LangChain callback handler. During one agent invocation it records
every chat-model call and tool call and then produces a compact nested span tree::

    {"name": "refund_agent", "type": "agent", "input": ..., "output": ...,
     "available_tools": [...],
     "children": [
        {"type": "llm",  "name": "model_call_1", "input": [new messages], "output": {...}},
        {"type": "tool", "name": "get_purchase_history", "input": {...}, "output": "..."},
        ...]}

The shape follows DeepEval's trace dictionaries (``name``/``type``/``input``/``output``/
``children``), which DeepEval's agentic metrics (task completion, step efficiency, plan
quality, plan adherence) serialise into their judge prompts. Intermediate LangGraph
chain nodes are flattened away so the judge sees the steps, not framework plumbing.
Each LLM span lists only the messages that are new since the previous call, which keeps
the trace small while preserving the whole conversation.

Recording our own trace (instead of DeepEval's ``CallbackHandler``) keeps TraceGrade
independent of DeepEval's global tracing state and of its cloud upload path, and lets the
UI display exactly what the judge saw.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

MAX_TEXT = 4000


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} chars clipped]"


def content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    data: dict[str, Any] = {"role": message.type, "content": _clip(content_text(message.content))}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        data["tool_calls"] = [{"name": tc["name"], "args": tc.get("args", {})} for tc in tool_calls]
    name = getattr(message, "name", None)
    if message.type == "tool" and name:
        data["tool_name"] = name
    return data


class TraceRecorder(BaseCallbackHandler):
    """Collects spans for a single agent invocation. Not reusable across invocations."""

    raise_error = False  # a recording bug must never break the agent run

    def __init__(self, available_tools: list[str] | None = None) -> None:
        self._lock = threading.Lock()
        self._spans: dict[UUID, dict[str, Any]] = {}
        self._order: list[UUID] = []
        self._starts: dict[UUID, float] = {}
        self._origin = time.perf_counter()
        self._messages_seen = 0
        self._llm_calls = 0
        self._available_tools = available_tools or []
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None

    # -- helpers ------------------------------------------------------------------
    def _offset_ms(self) -> float:
        return round((time.perf_counter() - self._origin) * 1000, 1)

    def _open(self, run_id: UUID, span: dict[str, Any]) -> None:
        with self._lock:
            span["start_ms"] = self._offset_ms()
            self._spans[run_id] = span
            self._order.append(run_id)
            self._starts[run_id] = time.perf_counter()

    def _close(self, run_id: UUID, **fields: Any) -> None:
        with self._lock:
            span = self._spans.get(run_id)
            if span is None:
                return
            span.update(fields)
            started = self._starts.pop(run_id, None)
            if started is not None:
                span["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)

    # -- chat models ----------------------------------------------------------------
    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        batch = messages[0] if messages else []
        new_messages = batch[self._messages_seen :] if self._messages_seen <= len(batch) else batch
        self._messages_seen = len(batch)
        self._llm_calls += 1
        params = kwargs.get("invocation_params") or {}
        model = params.get("model") or params.get("model_name") or params.get("_type")
        self._open(
            run_id,
            {
                "name": f"model_call_{self._llm_calls}",
                "type": "llm",
                "model": model,
                "input": [serialize_message(m) for m in new_messages],
            },
        )

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        output: dict[str, Any] = {}
        usage: dict[str, int] = {}
        if response.generations and response.generations[0]:
            generation = response.generations[0][0]
            message = getattr(generation, "message", None)
            if message is not None:
                output = serialize_message(message)
                output.pop("role", None)
                meta = getattr(message, "usage_metadata", None) or {}
                usage = {
                    k: int(v)
                    for k, v in meta.items()
                    if k.endswith("tokens") and isinstance(v, int)
                }
            else:
                output = {"content": _clip(generation.text)}
        if usage:
            with self._lock:
                self.input_tokens = (self.input_tokens or 0) + usage.get("input_tokens", 0)
                self.output_tokens = (self.output_tokens or 0) + usage.get("output_tokens", 0)
        self._close(run_id, output=output, **({"token_usage": usage} if usage else {}))

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._close(run_id, error=f"{type(error).__name__}: {_clip(str(error), 500)}")

    # -- tools ----------------------------------------------------------------------
    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        self._open(
            run_id,
            {"name": name, "type": "tool", "input": inputs if inputs is not None else input_str},
        )

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        content = getattr(output, "content", output)
        self._close(run_id, output=_clip(content_text(content)))

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._close(run_id, error=f"{type(error).__name__}: {_clip(str(error), 500)}")

    # -- result ---------------------------------------------------------------------
    def tool_spans(self) -> list[dict[str, Any]]:
        """Recorded tool calls in order; used as evidence when the agent run failed."""
        with self._lock:
            return [dict(self._spans[r]) for r in self._order if self._spans[r]["type"] == "tool"]

    def build(self, user_input: str, final_output: str | None) -> dict[str, Any]:
        with self._lock:
            children = [self._spans[run_id] for run_id in self._order]
        return {
            "name": "refund_agent",
            "type": "agent",
            "input": user_input,
            "output": final_output,
            "available_tools": list(self._available_tools),
            "children": children,
        }

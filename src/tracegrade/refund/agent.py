"""Assembly of the refund agent (the system under test).

The agent is LangChain's ``create_agent`` graph: a model node that may call tools, a tool
node, and a structured ``AgentReply`` response. ``build_refund_agent`` wires a chat model to a
fresh set of tools bound to a :class:`RefundToolContext`.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from tracegrade.refund.prompts import REFUND_AGENT_SYSTEM_PROMPT, REPLY_TOOL_INSTRUCTION
from tracegrade.refund.schemas import AgentReply, ReplyResponseTool
from tracegrade.refund.tools import RefundToolContext, build_refund_tools

#: Chat-model classes for which LangChain's provider-native structured output is used.
NATIVE_STRUCTURED_OUTPUT_MODELS = frozenset({"ChatOpenAI"})

_TRANSIENT_ERROR_NAMES = frozenset(
    {"RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError"}
)


def is_retryable_model_error(exc: Exception) -> bool:
    """Model-call failures worth retrying.

    Rate limits, timeouts, connection problems and 5xx responses are transient. Groq's
    ``tool_use_failed`` / ``output_parse_failed`` (HTTP 400) mean the model *generated* an
    invalid tool call or unparsable output; a fresh sample often succeeds. Retrying a model
    call is safe: no tool has run for that step. Exhausted *daily* quotas are not retried:
    the provider's wait time is minutes to hours.
    """
    text = str(exc).lower()
    if "per day" in text or "(tpd)" in text or "(rpd)" in text:
        return False
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    if status == 400 and any(
        code in str(exc) for code in ("tool_use_failed", "output_parse_failed")
    ):
        return True
    return type(exc).__name__ in _TRANSIENT_ERROR_NAMES


def build_refund_agent(
    model: BaseChatModel,
    context: RefundToolContext,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    system_prompt: str = REFUND_AGENT_SYSTEM_PROMPT,
    model_retries: int = 0,
) -> Any:
    """Return a compiled LangGraph agent for one session.

    The structured ``AgentReply`` is requested through a response *tool* (named ``reply``) for
    every model except OpenAI's, which supports native structured output together with tool
    calling. Groq rejects JSON mode combined with tools (HTTP 400 "json mode cannot be
    combined with tool/function calling", observed in live verification), and LangChain's
    automatic strategy selects JSON mode for some Groq models.

    ``model_retries`` > 0 adds a retry middleware around each model call (exponential
    backoff from 2 s, capped at 30 s) for the errors accepted by
    :func:`is_retryable_model_error`.
    """
    native = type(model).__name__ in NATIVE_STRUCTURED_OUTPUT_MODELS
    response_format: Any = AgentReply if native else ToolStrategy(ReplyResponseTool)
    middleware = (
        [
            ModelRetryMiddleware(
                max_retries=model_retries,
                retry_on=is_retryable_model_error,
                on_failure="error",
                initial_delay=2.0,
                backoff_factor=2.0,
                max_delay=30.0,
            )
        ]
        if model_retries > 0
        else []
    )
    return create_agent(
        model=model,
        tools=build_refund_tools(context),
        system_prompt=system_prompt if native else system_prompt + REPLY_TOOL_INSTRUCTION,
        response_format=response_format,
        checkpointer=checkpointer,
        middleware=middleware,
    )

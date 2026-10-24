"""Structured input/output contracts of the refund agent."""

from __future__ import annotations

from pydantic import BaseModel, Field, create_model


class AgentReply(BaseModel):
    """The agent's final reply for one customer turn."""

    message: str = Field(description="The text shown to the customer.")
    awaiting_customer: bool = Field(
        default=True,
        description=(
            "True while the agent needs more information from the customer (for example a "
            "customer ID or which items to refund). False once the request is resolved."
        ),
    )


class PurchaseItem(BaseModel):
    """One item named in a refund calculation request."""

    name: str = Field(description="Item name exactly as it appears in the purchase history.")


#: Name of the tool through which the agent returns its structured reply (LangChain's tool
#: strategy names the tool after the schema). Short and lower-case on purpose: some models
#: (gpt-oss on Groq, observed in live verification) call lower-case tool names even when the
#: declared name is capitalised, which the provider rejects. Excluded from "tools called".
RESPONSE_TOOL_NAME = "reply"

#: ``AgentReply`` under the response-tool name; instances are still ``AgentReply``.
ReplyResponseTool: type[AgentReply] = create_model(RESPONSE_TOOL_NAME, __base__=AgentReply)

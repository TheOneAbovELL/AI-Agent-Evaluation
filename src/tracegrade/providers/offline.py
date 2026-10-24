"""Offline, deterministic stand-in for an LLM.

``OfflinePolicyChatModel`` is a LangChain chat model that decides each step with plain
rules instead of a neural network. It plugs into the *real* agent graph: it emits real
tool calls, the real tools execute against the real purchase records, and the run is
traced and scored exactly like an LLM-backed run.

Purpose:
* a credential-free path to exercise the whole pipeline (CLI, engine, metrics, storage,
  UI) end to end;
* a reproducible baseline in tests;
* the ``naive`` variant reproduces a typical failure mode (it never checks purchase dates)
  so deterministic metrics have something to catch without any API calls.

It is NOT a model of LLM quality. Its scores say the pipeline works and the dataset is
consistent; they say nothing about how a real model would behave. Every run records the
provider as ``offline`` and the UI labels such runs accordingly.

The message parsing is deliberately simple (regular expressions over English phrasing
like "please refund the webcam and the USB hub"); it handles the bundled dataset and similar
phrasings, not arbitrary language.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from tracegrade.refund.policy import ItemStatus, classify_purchase_age
from tracegrade.refund.records import normalize_item_name
from tracegrade.refund.schemas import RESPONSE_TOOL_NAME

OFFLINE_VARIANTS = ("reference", "naive")

_CUSTOMER_ID = re.compile(r"\b(C\d{3,})\b", re.IGNORECASE)
_CUSTOMER_ID_PHRASE = re.compile(r"\bcustomer\s+id\s+(?:is\s+)?([A-Za-z0-9_-]+)", re.IGNORECASE)
_REFUND_KEYWORD = re.compile(r"\b(?:refund(?:ed|s)?|return(?:ed|ing|s)?)\b", re.IGNORECASE)
_INFO_REQUEST = re.compile(
    r"\bno refund\b|\bjust want to know\b|\bwhat (?:did )?i (?:purchased|bought|buy)\b"
    r"|\bpurchase history\b|\bwhat have i (?:bought|purchased)\b",
    re.IGNORECASE,
)
_QUOTE_REQUEST = re.compile(r"\bhow much\b|\bquote\b", re.IGNORECASE)
_CLAUSE_BREAK = re.compile(r"[.?!;]|\b(?:but|if|because|since|so|though)\b", re.IGNORECASE)
_PIECE_SPLIT = re.compile(r",|&|\band\b|\bplus\b", re.IGNORECASE)
_FILLER = frozenset(
    [
        "the",
        "my",
        "a",
        "an",
        "for",
        "of",
        "only",
        "me",
        "please",
        "to",
        "get",
        "back",
        "item",
        "items",
        "i",
        "bought",
        "purchased",
        "just",
        "both",
        "yet",
        "now",
        "it",
        "them",
        "this",
        "that",
        "these",
        "those",
        "also",
        "as",
        "well",
        "too",
        "which",
        "in",
        "on",
        "request",
        "like",
        "would",
        "want",
        "some",
        "money",
        "full",
        "issue",
        "give",
        "is",
        "was",
        "were",
        "be",
        "all",
        "you",
        "your",
        "can",
        "could",
        "d",
        "m",
        "s",
        "t",
        "ve",
        "ll",
        "re",
    ]
)


def _new_call_id(messages: Sequence[BaseMessage]) -> str:
    # Deterministic ids keep traces reproducible across runs.
    return f"offline_call_{len(messages)}"


def _parse_json(content: object) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    try:
        parsed = json.loads(str(content))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_customer_id(text: str) -> str | None:
    """Last customer ID mentioned, upper-cased (IDs are matched case-insensitively)."""
    found = _CUSTOMER_ID.findall(text) or _CUSTOMER_ID_PHRASE.findall(text)
    return found[-1].upper() if found else None


def extract_requested_items(text: str) -> list[str]:
    """Normalised item names that follow refund/return keywords (order preserved)."""
    items: list[str] = []
    for match in _REFUND_KEYWORD.finditer(text):
        tail = text[match.end() :]
        clause = _CLAUSE_BREAK.split(tail, maxsplit=1)[0]
        for piece in _PIECE_SPLIT.split(clause):
            words = [
                w
                for w in re.findall(r"[a-z0-9_$]+", piece.lower())
                if w not in _FILLER and not re.fullmatch(r"\$?\d+(?:\.\d+)?", w)
            ]
            name = normalize_item_name(" ".join(words))
            if name and name not in items:
                items.append(name)
    return items


def _match_purchase(candidate: str, purchased: dict[str, Any]) -> str | None:
    if candidate in purchased:
        return candidate
    singular = candidate[:-1] if candidate.endswith("s") else None
    if singular and singular in purchased:
        return singular
    return None


class OfflinePolicyChatModel(BaseChatModel):
    """Rule-based chat model that follows (``reference``) or ignores (``naive``) the policy."""

    variant: Literal["reference", "naive"] = "reference"
    window_days: int = 30

    @property
    def _llm_type(self) -> str:
        return "tracegrade-offline"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"variant": self.variant}

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> OfflinePolicyChatModel:
        # The rules already know the four refund tools and the response tool.
        return self

    # ------------------------------------------------------------------ decisions --
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._decide(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _tool_call(
        self, messages: Sequence[BaseMessage], note: str, name: str, args: dict[str, Any]
    ) -> AIMessage:
        return AIMessage(
            content=note,
            tool_calls=[
                {"name": name, "args": args, "id": _new_call_id(messages), "type": "tool_call"}
            ],
        )

    def _final(self, messages: Sequence[BaseMessage], answer: str, awaiting: bool) -> AIMessage:
        return self._tool_call(
            messages,
            "Responding to the customer.",
            RESPONSE_TOOL_NAME,
            {"message": answer, "awaiting_customer": awaiting},
        )

    def _decide(self, messages: list[BaseMessage]) -> AIMessage:
        human_texts = [str(m.content) for m in messages if isinstance(m, HumanMessage)]
        last_human = max(
            (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1
        )
        results: dict[str, dict[str, Any]] = {}
        for m in messages[last_human + 1 :]:
            if isinstance(m, ToolMessage) and m.name:
                results[m.name] = _parse_json(m.content)

        conversation_text = " . ".join(human_texts)
        customer = None
        for text in reversed(human_texts):
            customer = extract_customer_id(text)
            if customer:
                break
        if customer is None:
            return self._final(
                messages,
                "I can help with that. Could you please tell me your customer ID first "
                "(for example C1001)?",
                True,
            )

        history = results.get("get_purchase_history")
        if history is None:
            return self._tool_call(
                messages,
                f"Plan: identify customer {customer}, then check the requested items against the "
                "purchase history and the refund policy.",
                "get_purchase_history",
                {"customer_id": customer},
            )
        if history.get("status") != "found":
            return self._final(
                messages,
                f"I couldn't find a customer with the ID '{customer}'. Please check it and send me "
                "a valid customer ID.",
                True,
            )
        purchases: dict[str, dict[str, Any]] = history.get("purchases", {})

        if _INFO_REQUEST.search(conversation_text) or (
            not _REFUND_KEYWORD.search(conversation_text)
            and not _QUOTE_REQUEST.search(conversation_text)
        ):
            listing = ", ".join(
                f"{item} (${p['price']:.2f}, purchased {p['date']})"
                for item, p in purchases.items()
            )
            return self._final(
                messages,
                f"Here is your purchase history: {listing}. No refund ticket has been issued.",
                False,
            )

        candidates = extract_requested_items(conversation_text)
        if not candidates:
            # Fall back to item names mentioned anywhere in the conversation.
            lowered = normalize_item_name(conversation_text)
            candidates = [item for item in purchases if item in lowered]
        requested = [c for c in (_match_purchase(c, purchases) for c in candidates) if c]
        not_purchased = [c for c in candidates if _match_purchase(c, purchases) is None]

        if not candidates:
            names = ", ".join(purchases)
            return self._final(
                messages,
                f"Which items would you like to refund? Your purchases are: {names}.",
                True,
            )
        if not requested:
            return self._final(
                messages,
                "No refund will be issued because there is no purchase of "
                f"{', '.join(not_purchased)} in your history.",
                False,
            )

        ineligible: dict[str, str] = {name: "not purchased" for name in not_purchased}
        if self.variant == "reference":
            today_result = results.get("get_current_date")
            if today_result is None:
                return self._tool_call(
                    messages,
                    "Checking today's date to apply the 30-day refund window.",
                    "get_current_date",
                    {},
                )
            today = date.fromisoformat(str(today_result["today"]))
            eligible: list[str] = []
            for name in requested:
                status, age = classify_purchase_age(
                    date.fromisoformat(purchases[name]["date"]), today, self.window_days
                )
                if status is ItemStatus.ELIGIBLE:
                    eligible.append(name)
                elif status is ItemStatus.FUTURE_PURCHASE:
                    ineligible[name] = "its purchase date is after today's date"
                else:
                    ineligible[name] = (
                        f"it was purchased {age} days ago, outside the "
                        f"{self.window_days}-day refund window"
                    )
        else:  # naive: skips the date check entirely
            eligible = list(requested)

        reasons = "; ".join(f"{k}: {v}" for k, v in ineligible.items())
        if not eligible:
            return self._final(messages, f"No refund will be issued. {reasons}.", False)

        quote = results.get("calculate_refund")
        if quote is None:
            return self._tool_call(
                messages,
                f"Calculating the refund for the eligible items: {', '.join(eligible)}.",
                "calculate_refund",
                {"customer_id": customer, "items": [{"name": n} for n in eligible]},
            )
        amount = Decimal(str(quote.get("amount", 0)))
        not_refunded = f" Not refunded: {reasons}." if reasons else ""

        if _QUOTE_REQUEST.search(conversation_text):
            return self._final(
                messages,
                f"A refund for {', '.join(eligible)} would be ${amount:.2f}. As requested, no "
                f"refund ticket has been issued.{not_refunded}",
                False,
            )
        if amount <= 0:
            return self._final(
                messages,
                f"No refund will be issued because no eligible amount was found.{not_refunded}",
                False,
            )

        ticket = results.get("issue_refund_ticket")
        if ticket is None:
            return self._tool_call(
                messages,
                f"Issuing a refund ticket for ${amount:.2f}.",
                "issue_refund_ticket",
                {"customer_id": customer, "amount": float(amount)},
            )
        if ticket.get("status") != "issued":
            return self._final(
                messages,
                f"I could not issue the refund ticket: {ticket.get('reason', 'unknown error')}.",
                False,
            )
        return self._final(
            messages,
            f"A refund ticket ({ticket.get('ticket_id')}) for ${amount:.2f} has been issued for "
            f"{', '.join(eligible)}. It should arrive in your bank account soon.{not_refunded}",
            False,
        )

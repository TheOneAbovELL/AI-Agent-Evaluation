"""Use any LangChain chat model as a DeepEval judge.

DeepEval ships native judges for some providers (TraceGrade uses its native OpenAI judge).
For other providers, such as Groq, this adapter implements DeepEval's
``DeepEvalBaseLLM`` interface on top of a LangChain chat model:

* when DeepEval asks for a Pydantic schema, the adapter first tries LangChain's
  ``with_structured_output`` and returns a validated schema instance;
* if structured output fails, it falls back to a plain completion and returns the raw
  text, which DeepEval then parses as JSON itself (and reports a clear error if it is not
  valid JSON). Malformed judge output therefore becomes a metric *error*, never a score.
"""

from __future__ import annotations

from typing import Any

from deepeval.models import DeepEvalBaseLLM
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel

from tracegrade.logging_utils import get_logger

log = get_logger("providers.judge")


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)


class LangChainJudgeModel(DeepEvalBaseLLM):
    def __init__(
        self,
        chat_model: BaseChatModel,
        model_name: str,
        structured_method: str | None = None,
    ) -> None:
        self._chat_model = chat_model
        self._model_name = model_name
        # LangChain's default (function calling) fails with some Groq models; Groq's
        # json_schema mode works without tools (verified live with openai/gpt-oss-120b).
        self._structured_kwargs: dict[str, Any] = (
            {"method": structured_method} if structured_method else {}
        )
        super().__init__(model=model_name)

    def load_model(self, *args: Any, **kwargs: Any) -> Any:
        return self._chat_model

    def get_model_name(self, *args: Any, **kwargs: Any) -> str:
        return self._model_name

    # DeepEval calls generate(prompt, schema=...) via generate_with_schema.
    def generate(self, prompt: str, schema: type[BaseModel] | None = None, **kwargs: Any) -> Any:
        if schema is not None:
            try:
                result = self._chat_model.with_structured_output(
                    schema, **self._structured_kwargs
                ).invoke(prompt)
                if isinstance(result, schema):
                    return result
            except Exception as exc:  # fall back to raw JSON parsing by DeepEval
                log.info(
                    "structured judge output failed; falling back to raw text",
                    extra={"ctx": {"schema": schema.__name__, "error": type(exc).__name__}},
                )
        return _text(self._chat_model.invoke(prompt).content)

    async def a_generate(
        self, prompt: str, schema: type[BaseModel] | None = None, **kwargs: Any
    ) -> Any:
        if schema is not None:
            try:
                result = await self._chat_model.with_structured_output(
                    schema, **self._structured_kwargs
                ).ainvoke(prompt)
                if isinstance(result, schema):
                    return result
            except Exception as exc:
                log.info(
                    "structured judge output failed; falling back to raw text",
                    extra={"ctx": {"schema": schema.__name__, "error": type(exc).__name__}},
                )
        response = await self._chat_model.ainvoke(prompt)
        return _text(response.content)

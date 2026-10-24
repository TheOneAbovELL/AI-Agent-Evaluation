"""Deterministic test doubles for LLM judges (no network)."""

from __future__ import annotations

import types
from typing import Any, Literal, Union, get_args, get_origin

from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel


def _value(annotation: Any, name: str, score: float) -> Any:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        options = [a for a in get_args(annotation) if a is not type(None)]
        return _value(options[0], name, score) if options else None
    if origin is Literal:
        choices = get_args(annotation)
        return "yes" if "yes" in choices else choices[0]
    if origin in (list, tuple, set):
        return []
    if origin is dict:
        return {}
    if annotation is float:
        return score
    if annotation is int:
        return round(score * 10)
    if annotation is bool:
        return True
    if annotation is str:
        return "yes" if name == "verdict" else f"fake {name}"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return fill_schema(annotation, score)
    return None


def fill_schema(schema: type[BaseModel], score: float) -> BaseModel:
    return schema.model_validate(
        {name: _value(field.annotation, name, score) for name, field in schema.model_fields.items()}
    )


class SchemaFillingJudge(DeepEvalBaseLLM):
    """Answers every DeepEval schema request with a plausible, fixed instance.

    It lets tests drive DeepEval's real metric classes end to end. The scores it yields are
    meaningless by construction and are only used to check plumbing.
    """

    def __init__(self, score: float = 0.9, fail_with: BaseException | None = None) -> None:
        self.score = score
        self.fail_with = fail_with
        self.calls = 0
        super().__init__(model="fake-judge")

    def load_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_model_name(self, *args: Any, **kwargs: Any) -> str:
        return "fake-judge"

    def generate(self, prompt: str, schema: type[BaseModel] | None = None, **kwargs: Any) -> Any:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        if schema is None:
            return '{"reason": "fake", "score": 9}'
        return fill_schema(schema, self.score)

    async def a_generate(
        self, prompt: str, schema: type[BaseModel] | None = None, **kwargs: Any
    ) -> Any:
        return self.generate(prompt, schema=schema, **kwargs)

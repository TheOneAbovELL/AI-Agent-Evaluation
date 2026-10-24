"""Evaluation dataset schema, loading and validation.

A dataset is one JSON document that is self-contained: it holds the purchase records the
agent's tools read, the reference date used as "today", and the cases. Keeping data and
expectations together means a dataset file plus its SHA-256 fully identifies the inputs
of a run.

Case fields
-----------
``input``                 the customer message sent to the agent.
``expected_output``       a reference answer (used by the LLM answer-correctness judge).
``expected_tools``        tools the agent is expected to call; ``input_parameters`` is
                          optional per tool (omit it to check the name only).
``forbidden_tools``       tools that must not be called (e.g. no ticket for a quote).
``expected_refund_total`` ground-truth refund outcome. ``0`` = no ticket may be issued;
                          a positive number = tickets must total exactly this amount;
                          omitted/``null`` = not checked.
``customer`` / ``requested_items``
                          optional oracle metadata: lets the test-suite recompute
                          ``expected_refund_total`` from the policy code.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from tracegrade.errors import DatasetError
from tracegrade.refund.records import Purchase, PurchaseRecords
from tracegrade.refund.tools import TOOL_NAMES

_CASE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
BUNDLED_DATASETS_PACKAGE = "tracegrade.resources.datasets"


class ExpectedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    input_parameters: dict[str, Any] | None = None


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    input: str = Field(min_length=1, max_length=4000)
    expected_output: str | None = Field(default=None, max_length=4000)
    expected_tools: list[ExpectedToolCall] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_refund_total: float | None = Field(default=None, ge=0)
    customer: str | None = None
    requested_items: list[str] | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _CASE_ID.match(value):
            raise ValueError("case id must be 1-80 chars of lowercase letters, digits, '-' or '_'")
        return value

    @model_validator(mode="after")
    def _check_tools(self) -> EvalCase:
        expected = {t.name for t in self.expected_tools}
        overlap = expected.intersection(self.forbidden_tools)
        if overlap:
            raise ValueError(f"tools both expected and forbidden: {sorted(overlap)}")
        return self


class EvalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    reference_date: date
    refund_window_days: int = Field(default=30, ge=0, le=3650)
    customers: dict[str, dict[str, Purchase]]
    cases: list[EvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> EvalDataset:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for c in self.cases:
            if c.id in seen:
                duplicates.add(c.id)
            seen.add(c.id)
        if duplicates:
            raise ValueError(f"duplicate case ids: {sorted(duplicates)}")
        return self

    def records(self) -> PurchaseRecords:
        return PurchaseRecords(self.customers)

    def case(self, case_id: str) -> EvalCase:
        for c in self.cases:
            if c.id == case_id:
                return c
        raise DatasetError(f"Dataset '{self.name}' has no case '{case_id}'.")

    def select(self, case_ids: list[str] | None) -> list[EvalCase]:
        if not case_ids:
            return list(self.cases)
        return [self.case(cid) for cid in case_ids]

    def warnings(self) -> list[str]:
        """Non-fatal issues worth showing to the user (unknown tool names, ...)."""
        out: list[str] = []
        known = set(TOOL_NAMES)
        for c in self.cases:
            for name in [t.name for t in c.expected_tools] + c.forbidden_tools:
                if name not in known:
                    out.append(f"case '{c.id}': tool '{name}' is not one of the agent's tools")
            if c.expected_output is None:
                out.append(f"case '{c.id}': no expected_output, answer-correctness is skipped")
        return out


class LoadedDataset(BaseModel):
    """A validated dataset plus provenance (where it came from and its content hash)."""

    dataset: EvalDataset
    source: str
    sha256: str


def _validation_message(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors()[:20]:
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"{loc}: {err['msg']}")
    more = len(exc.errors()) - 20
    if more > 0:
        lines.append(f"... and {more} more problem(s)")
    return "\n  ".join(lines)


def parse_dataset(raw: bytes, source: str, max_bytes: int | None = None) -> LoadedDataset:
    if max_bytes is not None and len(raw) > max_bytes:
        raise DatasetError(
            f"Dataset '{source}' is {len(raw):,} bytes; the limit is {max_bytes:,} bytes."
        )
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise DatasetError(f"Dataset '{source}' is not UTF-8 text.") from None
    except json.JSONDecodeError as exc:
        raise DatasetError(
            f"Dataset '{source}' is not valid JSON (line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg})."
        ) from None
    if not isinstance(payload, dict):
        raise DatasetError(f"Dataset '{source}' must be a JSON object.")
    try:
        dataset = EvalDataset.model_validate(payload)
        dataset.records()  # duplicate/empty names after normalisation
    except ValidationError as exc:
        raise DatasetError(
            f"Dataset '{source}' failed validation:\n  {_validation_message(exc)}"
        ) from None
    except ValueError as exc:
        raise DatasetError(f"Dataset '{source}' has invalid customers: {exc}") from None
    return LoadedDataset(dataset=dataset, source=source, sha256=hashlib.sha256(raw).hexdigest())


def load_dataset(path: Path, max_bytes: int | None = None) -> LoadedDataset:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise DatasetError(f"Dataset file not found: {path}") from None
    except OSError as exc:
        raise DatasetError(f"Cannot read dataset file {path}: {exc}") from None
    return parse_dataset(raw, source=str(path), max_bytes=max_bytes)


def bundled_dataset_names() -> list[str]:
    root = files(BUNDLED_DATASETS_PACKAGE)
    return sorted(p.name[:-5] for p in root.iterdir() if p.name.endswith(".json"))


def load_bundled_dataset(name: str = "refund_support_v1") -> LoadedDataset:
    if name not in bundled_dataset_names():
        raise DatasetError(
            f"No bundled dataset named '{name}'. Available: {', '.join(bundled_dataset_names())}."
        )
    raw = files(BUNDLED_DATASETS_PACKAGE).joinpath(f"{name}.json").read_bytes()
    return parse_dataset(raw, source=f"bundled:{name}")


def resolve_dataset(spec: str, max_bytes: int | None = None) -> LoadedDataset:
    """``bundled:<name>``, a bare bundled name, or a filesystem path to a JSON file."""
    if spec.startswith("bundled:"):
        return load_bundled_dataset(spec.removeprefix("bundled:"))
    path = Path(spec)
    if path.suffix.lower() != ".json" and spec in bundled_dataset_names():
        return load_bundled_dataset(spec)
    return load_dataset(path, max_bytes=max_bytes)

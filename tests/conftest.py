"""Shared fixtures.

Every test runs in a temporary working directory with provider credentials removed from
the environment, so the developer's real ``.env`` and API keys can never leak into (or be
spent by) the default test run. Live-provider tests opt back in explicitly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from tracegrade.config import Settings, get_settings, load_settings
from tracegrade.evaluation.dataset import LoadedDataset, load_bundled_dataset
from tracegrade.evaluation.engine import EvaluationEngine
from tracegrade.evaluation.storage import RunStore
from tracegrade.logging_utils import LOGGER_NAME

CREDENTIAL_VARS = ("OPENAI_API_KEY", "GROQ_API_KEY")
LIVE = os.environ.get("TRACEGRADE_RUN_LIVE_TESTS") == "1"
_SAVED_KEYS = {name: os.environ.get(name) for name in CREDENTIAL_VARS}


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("TRACEGRADE_"):
            monkeypatch.delenv(name, raising=False)
    for name in CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
    # The CLI configures the "tracegrade" logger with handlers bound to the (captured)
    # stderr of that test; reset so later tests log through pytest normally.
    app_logger = logging.getLogger(LOGGER_NAME)
    for handler in list(app_logger.handlers):
        app_logger.removeHandler(handler)
    app_logger.propagate = True


@pytest.fixture
def live_keys(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Restore real credentials for live tests only."""
    restored = {}
    for name, value in _SAVED_KEYS.items():
        if value:
            monkeypatch.setenv(name, value)
            restored[name] = value
    get_settings.cache_clear()
    return restored


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(runs_dir=tmp_path / "runs", datasets_dir=tmp_path / "datasets")


@pytest.fixture(scope="session")
def bundled() -> LoadedDataset:
    return load_bundled_dataset()


@pytest.fixture
def store(settings: Settings) -> RunStore:
    return RunStore(settings.runs_dir)


@pytest.fixture
def engine(settings: Settings, store: RunStore) -> EvaluationEngine:
    return EvaluationEngine(settings, store, judge_backoff_seconds=0.0)


class FailingChatModel(BaseChatModel):
    """Raises like a provider would on an authentication failure."""

    message: str = "Error code: 401 - invalid api key sk-abcdefghijklmnopqrstuvwxyz123456"

    @property
    def _llm_type(self) -> str:
        return "failing"

    def bind_tools(self, tools: Any, **kwargs: Any) -> FailingChatModel:  # type: ignore[override]
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        raise PermissionError(self.message)


class SlowChatModel(BaseChatModel):
    """Never answers within a short timeout."""

    delay: float = 5.0

    @property
    def _llm_type(self) -> str:
        return "slow"

    def bind_tools(self, tools: Any, **kwargs: Any) -> SlowChatModel:  # type: ignore[override]
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        raise NotImplementedError

    async def _agenerate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        await asyncio.sleep(self.delay)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="late"))])


class LoopingChatModel(BaseChatModel):
    """Calls the same tool forever (a tool-calling loop)."""

    @property
    def _llm_type(self) -> str:
        return "looping"

    def bind_tools(self, tools: Any, **kwargs: Any) -> LoopingChatModel:  # type: ignore[override]
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        call = {
            "name": "get_current_date",
            "args": {},
            "id": f"loop_{len(messages)}",
            "type": "tool_call",
        }
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[call]))]
        )

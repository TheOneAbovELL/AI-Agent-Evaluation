from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import BaseModel

from tracegrade.config import PolicyMode, get_settings, load_settings
from tracegrade.errors import ConfigurationError, ProviderUnavailableError
from tracegrade.logging_utils import RedactingFilter, configure_logging, redact
from tracegrade.providers.judge_adapter import LangChainJudgeModel
from tracegrade.providers.offline import OfflinePolicyChatModel
from tracegrade.providers.registry import (
    ModelSpec,
    build_chat_model,
    build_judge,
    check_connection,
    default_agent_spec,
    default_judge_spec,
    provider_status,
)

FAKE_GROQ = "gsk_" + "t" * 40
FAKE_OPENAI = "sk-" + "t" * 40


def test_defaults_work_without_any_configuration() -> None:
    s = load_settings()
    assert (s.agent_provider, s.agent_model, s.judge_provider) == ("offline", "reference", "none")
    assert s.policy_mode is PolicyMode.ENFORCED and s.openai_api_key is None
    assert default_judge_spec(s) is None and default_agent_spec(s).label == "offline:reference"


def test_env_and_dotenv_are_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        f'TRACEGRADE_AGENT_PROVIDER=groq\nGROQ_API_KEY="{FAKE_GROQ}"\nOPENAI_API_KEY=""\n'
        "TRACEGRADE_AGENT_TEMPERATURE=\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRACEGRADE_MAX_CONCURRENCY", "4")
    s = get_settings()
    assert s.agent_provider == "groq" and s.max_concurrency == 4
    assert s.groq_api_key is not None and s.groq_api_key.get_secret_value() == FAKE_GROQ
    assert s.openai_api_key is None  # blank means not configured
    assert s.agent_temperature is None
    assert FAKE_GROQ not in repr(s) and FAKE_GROQ not in str(s.model_dump())


@pytest.mark.parametrize(
    ("env", "fragment"),
    [
        ({"TRACEGRADE_AGENT_PROVIDER": "bard"}, "TRACEGRADE_AGENT_PROVIDER"),
        ({"TRACEGRADE_MAX_CONCURRENCY": "0"}, "TRACEGRADE_MAX_CONCURRENCY"),
        ({"TRACEGRADE_POLICY_MODE": "lenient"}, "TRACEGRADE_POLICY_MODE"),
    ],
)
def test_invalid_configuration_messages(
    monkeypatch: pytest.MonkeyPatch, env: dict, fragment: str
) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigurationError, match=fragment):
        load_settings()


def test_redaction() -> None:
    text = (
        f"key {FAKE_OPENAI} and {FAKE_GROQ} and Bearer abcdefghijklmnopqrstuvwx "
        "and custom-secret-123"
    )
    out = redact(text, ["custom-secret-123"])
    for secret in (FAKE_OPENAI, FAKE_GROQ, "abcdefghijklmnopqrstuvwx", "custom-secret-123"):
        assert secret not in out


def test_log_records_are_redacted() -> None:
    logger = configure_logging("INFO", "json", None, [])
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter(["my-literal-secret"]))
    logger.addHandler(handler)
    logger.getChild("t").warning(
        "leaked %s", FAKE_OPENAI, extra={"ctx": {"k": "my-literal-secret"}}
    )
    logger.removeHandler(handler)
    assert FAKE_OPENAI not in stream.getvalue()


def test_provider_status_without_keys() -> None:
    status = {s.name: s for s in provider_status(load_settings())}
    assert status["offline"].usable
    assert not status["groq"].usable and "GROQ_API_KEY" in status["groq"].message
    assert not status["openai"].usable


def test_build_models_offline_and_errors() -> None:
    s = load_settings()
    model = build_chat_model(ModelSpec(provider="offline", model="naive"), s)
    assert isinstance(model, OfflinePolicyChatModel) and model.variant == "naive"
    with pytest.raises(ConfigurationError, match="Offline model must be one of"):
        build_chat_model(ModelSpec(provider="offline", model="gpt"), s)
    with pytest.raises(ProviderUnavailableError, match="GROQ_API_KEY"):
        build_chat_model(ModelSpec(provider="groq", model="m"), s)
    with pytest.raises(ConfigurationError, match="Unknown provider"):
        build_chat_model(ModelSpec(provider="bard", model="m"), s)
    with pytest.raises(ConfigurationError, match="cannot be used as an LLM judge"):
        build_judge(ModelSpec(provider="offline", model="reference"), s)
    assert check_connection(ModelSpec(provider="offline", model="reference"), s).startswith(
        "Offline"
    )


def test_build_real_clients_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", FAKE_GROQ)
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI)
    s = load_settings()
    groq = build_chat_model(
        ModelSpec(provider="groq", model="openai/gpt-oss-120b", temperature=None), s
    )
    from langchain_groq import ChatGroq

    assert isinstance(groq, ChatGroq) and groq.model_name == "openai/gpt-oss-120b"
    openai = build_chat_model(ModelSpec(provider="openai", model="gpt-5.4", max_retries=3), s)
    assert type(openai).__name__ == "ChatOpenAI" and openai.max_retries == 3
    judge = build_judge(ModelSpec(provider="openai", model="gpt-5.4"), s)
    assert type(judge).__name__ == "OpenAIModel"
    groq_judge = build_judge(ModelSpec(provider="groq", model="openai/gpt-oss-120b"), s)
    assert isinstance(groq_judge, LangChainJudgeModel)
    assert groq_judge.get_model_name() == "groq:openai/gpt-oss-120b"


class Verdict(BaseModel):
    score: float
    reason: str


class StructuredFake(FakeListChatModel):
    structured: Any = None

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        outer = self

        class Runner:
            def invoke(self, prompt: Any) -> Any:
                if isinstance(outer.structured, Exception):
                    raise outer.structured
                return outer.structured

            async def ainvoke(self, prompt: Any) -> Any:
                return self.invoke(prompt)

        return Runner()


def test_judge_adapter_structured_and_fallback() -> None:
    ok = LangChainJudgeModel(
        StructuredFake(responses=["unused"], structured=Verdict(score=0.7, reason="r")), "x"
    )
    assert ok.generate("p", schema=Verdict) == Verdict(score=0.7, reason="r")
    fallback = LangChainJudgeModel(
        StructuredFake(
            responses=['{"score": 0.4, "reason": "raw"}'], structured=ValueError("no tools")
        ),
        "x",
    )
    assert fallback.generate("p", schema=Verdict) == '{"score": 0.4, "reason": "raw"}'
    plain = LangChainJudgeModel(StructuredFake(responses=["hello"]), "x")
    assert plain.generate("p") == "hello"
    import asyncio

    assert asyncio.run(ok.a_generate("p", schema=Verdict)).score == 0.7


def test_model_defaults_follow_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACEGRADE_AGENT_PROVIDER", "groq")
    monkeypatch.setenv("TRACEGRADE_JUDGE_PROVIDER", "openai")
    monkeypatch.setenv("TRACEGRADE_AGENT_MODEL", "  ")
    s = load_settings()
    assert s.agent_model == "qwen/qwen3.8-27b" and s.judge_model == "gpt-5.4"
    monkeypatch.setenv("TRACEGRADE_AGENT_MODEL", "llama-x")
    assert load_settings().agent_model == "llama-x"


def test_env_example_is_a_valid_configuration(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[2] / ".env.example"
    (tmp_path / ".env").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    s = get_settings()
    assert s.agent_provider == "offline" and s.agent_model == "reference"
    assert s.judge_provider == "none" and s.openai_api_key is None and s.groq_api_key is None

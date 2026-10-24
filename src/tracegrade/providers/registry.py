"""Provider registry: builds agent chat models and DeepEval judges from a ``ModelSpec``.

Supported providers
-------------------
=========  =====================  ====================  =============================
provider   agent model            judge                 credential
=========  =====================  ====================  =============================
offline    rule-based stand-in    (not available)       none
openai     ``ChatOpenAI``         DeepEval native judge ``OPENAI_API_KEY``
groq       ``ChatGroq``           LangChain adapter     ``GROQ_API_KEY``
=========  =====================  ====================  =============================

Building a model never makes a network call. ``check_connection`` makes one tiny call and
is only run on explicit user request (CLI ``doctor --ping`` or the Settings page button).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from tracegrade.config import DEFAULT_AGENT_MODELS, DEFAULT_JUDGE_MODELS, Settings
from tracegrade.errors import ConfigurationError, ProviderUnavailableError
from tracegrade.providers.offline import OFFLINE_VARIANTS, OfflinePolicyChatModel


class ModelSpec(BaseModel):
    """Serializable description of a model choice. Never contains credentials."""

    provider: str
    model: str
    temperature: float | None = Field(default=0.0, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    display_name: str
    package: str | None
    api_key_env: str | None
    default_agent_model: str
    default_judge_model: str | None
    supports_judge: bool
    notes: str


PROVIDERS: dict[str, ProviderInfo] = {
    "offline": ProviderInfo(
        name="offline",
        display_name="Offline reference model (rule-based, not an LLM)",
        package=None,
        api_key_env=None,
        default_agent_model=DEFAULT_AGENT_MODELS["offline"],
        default_judge_model=None,
        supports_judge=False,
        notes="Deterministic stand-in for pipeline checks. Variants: reference, naive.",
    ),
    "openai": ProviderInfo(
        name="openai",
        display_name="OpenAI",
        package="langchain_openai",
        api_key_env="OPENAI_API_KEY",
        default_agent_model=DEFAULT_AGENT_MODELS["openai"],
        default_judge_model=DEFAULT_JUDGE_MODELS["openai"],
        supports_judge=True,
        notes="Agent via langchain-openai; judge via DeepEval's native OpenAI model.",
    ),
    "groq": ProviderInfo(
        name="groq",
        display_name="Groq",
        package="langchain_groq",
        api_key_env="GROQ_API_KEY",
        default_agent_model=DEFAULT_AGENT_MODELS["groq"],
        default_judge_model=DEFAULT_JUDGE_MODELS["groq"],
        supports_judge=True,
        notes="Agent via langchain-groq; judge via the LangChain adapter. Pick a model "
        "with tool-calling support.",
    ),
}


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    display_name: str
    package_installed: bool
    credential_present: bool
    usable: bool
    message: str


def _package_installed(package: str | None) -> bool:
    return package is None or importlib.util.find_spec(package) is not None


def provider_status(settings: Settings) -> list[ProviderStatus]:
    statuses = []
    for info in PROVIDERS.values():
        installed = _package_installed(info.package)
        has_key = info.api_key_env is None or settings.api_key_for(info.name) is not None
        if not installed:
            message = f"Python package '{info.package}' is not installed."
        elif not has_key:
            message = f"{info.api_key_env} is not set."
        else:
            message = "Ready (credential present; not verified until a call is made)."
            if info.api_key_env is None:
                message = "Ready (no credential needed)."
        statuses.append(
            ProviderStatus(
                name=info.name,
                display_name=info.display_name,
                package_installed=installed,
                credential_present=has_key,
                usable=installed and has_key,
                message=message,
            )
        )
    return statuses


def _require(info: ProviderInfo, settings: Settings) -> str | None:
    if not _package_installed(info.package):
        raise ProviderUnavailableError(
            f"Provider '{info.name}' needs the Python package '{info.package}'.",
            hint="Run `uv sync` to install the project dependencies.",
        )
    if info.api_key_env is None:
        return None
    key = settings.api_key_for(info.name)
    if key is None:
        raise ProviderUnavailableError(
            f"Provider '{info.name}' needs {info.api_key_env}, which is not set.",
            hint=f"Add {info.api_key_env}=... to your .env file (see .env.example).",
        )
    return key.get_secret_value()


def get_provider(name: str) -> ProviderInfo:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ConfigurationError(
            f"Unknown provider '{name}'. Choose one of: {', '.join(PROVIDERS)}."
        ) from None


def build_chat_model(spec: ModelSpec, settings: Settings) -> BaseChatModel:
    """Chat model for the agent (or for the Groq judge adapter)."""
    info = get_provider(spec.provider)
    api_key = _require(info, settings)
    if info.name == "offline":
        if spec.model not in OFFLINE_VARIANTS:
            raise ConfigurationError(
                f"Offline model must be one of {', '.join(OFFLINE_VARIANTS)}, got '{spec.model}'."
            )
        return OfflinePolicyChatModel(variant=spec.model)  # type: ignore[arg-type]

    common: dict[str, Any] = {
        "model": spec.model,
        "timeout": spec.timeout_seconds,
        "max_retries": spec.max_retries,
        "api_key": api_key,
    }
    if spec.temperature is not None:
        common["temperature"] = spec.temperature
    if info.name == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(**common)
    if info.name == "groq":
        return _groq_chat_model_class()(**common)
    raise ConfigurationError(f"Provider '{info.name}' cannot build agent models.")


def _groq_chat_model_class() -> type[BaseChatModel]:
    """``ChatGroq`` that never forces a tool call.

    LangChain forces ``tool_choice="any"`` while it waits for the structured reply. When a
    model then answers in plain text, Groq rejects the whole response (HTTP 400 "Tool choice
    is required, but model did not call a tool"), observed in live verification right after a
    ticket had been issued. With ``"auto"`` the text answer is accepted; the engine records it
    as an answer without structured reply (with a warning) instead of losing the run.
    """
    from langchain_groq import ChatGroq

    class GroqChatModel(ChatGroq):
        def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Any:
            if tool_choice in ("any", "required"):
                tool_choice = "auto"
            return super().bind_tools(tools, tool_choice=tool_choice, **kwargs)

    return GroqChatModel


def build_judge(spec: ModelSpec, settings: Settings) -> Any:
    """A DeepEval judge model (``DeepEvalBaseLLM``) for the given spec."""
    info = get_provider(spec.provider)
    if not info.supports_judge:
        raise ConfigurationError(f"Provider '{info.name}' cannot be used as an LLM judge.")
    api_key = _require(info, settings)
    if info.name == "openai":
        from deepeval.models import OpenAIModel

        kwargs: dict[str, Any] = {"model": spec.model, "api_key": api_key}
        if spec.temperature is not None:
            kwargs["temperature"] = spec.temperature
        return OpenAIModel(**kwargs)
    from tracegrade.providers.judge_adapter import LangChainJudgeModel

    return LangChainJudgeModel(
        build_chat_model(spec, settings),
        model_name=spec.label,
        structured_method="json_schema" if info.name == "groq" else None,
    )


def check_connection(spec: ModelSpec, settings: Settings) -> str:
    """Make one minimal request. Raises on failure; returns a short confirmation."""
    if spec.provider == "offline":
        return "Offline model needs no connection."
    model = build_chat_model(spec, settings)
    reply = model.invoke("Reply with the single word: pong")
    return f"{spec.label} replied: {str(reply.content)[:60]!r}"


def default_agent_spec(settings: Settings) -> ModelSpec:
    return ModelSpec(
        provider=settings.agent_provider,
        model=settings.agent_model,
        temperature=settings.agent_temperature,
        timeout_seconds=settings.agent_timeout_seconds,
        max_retries=settings.agent_max_retries,
    )


def default_judge_spec(settings: Settings) -> ModelSpec | None:
    if settings.judge_provider == "none":
        return None
    return ModelSpec(
        provider=settings.judge_provider,
        model=settings.judge_model,
        temperature=0.0,
        timeout_seconds=settings.judge_timeout_seconds,
        max_retries=settings.judge_max_retries,
    )

"""Application settings.

Settings come from environment variables (optionally loaded from a ``.env`` file in the
current working directory). Every TraceGrade-specific variable uses the ``TRACEGRADE_``
prefix; provider credentials use the provider's conventional variable names
(``OPENAI_API_KEY``, ``GROQ_API_KEY``) so that existing shell setups keep working.

Credentials are stored as :class:`pydantic.SecretStr`, so they never appear in ``repr``,
logs, run records or exports.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tracegrade.errors import ConfigurationError

# DeepEval sends anonymous usage telemetry unless told otherwise. TraceGrade opts out by
# default; set DEEPEVAL_TELEMETRY_OPT_OUT=0 explicitly to re-enable it.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")


class PolicyMode(StrEnum):
    """How strictly the refund tools enforce the refund policy.

    ``enforced``     - tools validate eligibility and ticket amounts (guardrails).
    ``prompt_only``  - tools only look things up and sum prices; the policy lives solely
                       in the system prompt. Useful to measure how well the LLM follows
                       policy without guardrails.
    """

    ENFORCED = "enforced"
    PROMPT_ONLY = "prompt_only"


AGENT_PROVIDERS = ("offline", "openai", "groq")
JUDGE_PROVIDERS = ("none", "openai", "groq")

#: Model used when TRACEGRADE_AGENT_MODEL / TRACEGRADE_JUDGE_MODEL are unset or blank.
#: Provider model catalogues change over time; override these via the environment.
#: Groq: the agent default (Qwen) was the model that completed the live tool-calling checks
#: cleanly; the judge default is a different model family to avoid self-preference.
DEFAULT_AGENT_MODELS = {
    "offline": "reference",
    "openai": "gpt-5.4",
    "groq": "qwen/qwen3.8-27b",
}
DEFAULT_JUDGE_MODELS = {"none": "", "openai": "gpt-5.4", "groq": "openai/gpt-oss-120b"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACEGRADE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- system under test (the refund agent) -------------------------------------
    agent_provider: str = Field(default="offline", description="offline | openai | groq")
    agent_model: str = Field(default="", description="Blank = the provider's default model.")
    # Blank means "do not send a temperature" (some reasoning models reject the parameter).
    agent_temperature: float | None = Field(default=0.0, ge=0.0, le=2.0)
    agent_timeout_seconds: float = Field(default=300.0, gt=0, le=3600)
    agent_max_retries: int = Field(default=4, ge=0, le=10)
    agent_recursion_limit: int = Field(default=25, ge=5, le=200)
    policy_mode: PolicyMode = PolicyMode.ENFORCED

    # --- LLM-as-a-judge ------------------------------------------------------------
    judge_provider: str = Field(default="none", description="none | openai | groq")
    judge_model: str = Field(default="", description="Blank = the provider's default model.")
    judge_timeout_seconds: float = Field(default=180.0, gt=0, le=3600)
    judge_max_retries: int = Field(default=4, ge=0, le=10)

    # --- execution -----------------------------------------------------------------
    max_concurrency: int = Field(default=2, ge=1, le=16)

    # --- storage -------------------------------------------------------------------
    runs_dir: Path = Path("runs")
    datasets_dir: Path = Path("datasets")
    max_upload_bytes: int = Field(default=1_000_000, ge=1_000, le=50_000_000)

    # --- logging -------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["text", "json"] = "text"
    log_file: Path | None = None

    # --- credentials (conventional names, no prefix) ------------------------------
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    groq_api_key: SecretStr | None = Field(default=None, validation_alias="GROQ_API_KEY")

    @field_validator("agent_provider")
    @classmethod
    def _check_agent_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in AGENT_PROVIDERS:
            raise ValueError(f"must be one of {', '.join(AGENT_PROVIDERS)}")
        return value

    @field_validator("judge_provider")
    @classmethod
    def _check_judge_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in JUDGE_PROVIDERS:
            raise ValueError(f"must be one of {', '.join(JUDGE_PROVIDERS)}")
        return value

    @field_validator("agent_model", "judge_model")
    @classmethod
    def _strip_model_name(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _default_models(self) -> Settings:
        if not self.agent_model:
            self.agent_model = DEFAULT_AGENT_MODELS[self.agent_provider]
        if not self.judge_model:
            self.judge_model = DEFAULT_JUDGE_MODELS[self.judge_provider]
        return self

    @field_validator("openai_api_key", "groq_api_key", "agent_temperature", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value: object) -> object:
        # An empty string in .env (OPENAI_API_KEY="") means "not configured".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def api_key_for(self, provider: str) -> SecretStr | None:
        return {"openai": self.openai_api_key, "groq": self.groq_api_key}.get(provider)


def load_settings(**overrides: object) -> Settings:
    """Build settings, converting pydantic validation errors into a readable message."""
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            location = ".".join(str(part) for part in err["loc"]) or "settings"
            env_name = f"TRACEGRADE_{location.upper()}" if location != "settings" else location
            problems.append(f"{env_name}: {err['msg']}")
        raise ConfigurationError("Invalid configuration:\n  " + "\n  ".join(problems)) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings (cached). Call ``get_settings.cache_clear()`` after changes."""
    return load_settings()

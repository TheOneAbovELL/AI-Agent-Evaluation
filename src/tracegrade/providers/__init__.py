"""Model providers: agent chat models, DeepEval judges and the offline reference model."""

from tracegrade.providers.registry import (
    PROVIDERS,
    ModelSpec,
    ProviderInfo,
    ProviderStatus,
    build_chat_model,
    build_judge,
    check_connection,
    default_agent_spec,
    default_judge_spec,
    get_provider,
    provider_status,
)

__all__ = [
    "PROVIDERS",
    "ModelSpec",
    "ProviderInfo",
    "ProviderStatus",
    "build_chat_model",
    "build_judge",
    "check_connection",
    "default_agent_spec",
    "default_judge_spec",
    "get_provider",
    "provider_status",
]

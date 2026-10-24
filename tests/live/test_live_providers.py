"""Live provider tests: real API calls, real (small) cost.

Skipped unless ``TRACEGRADE_RUN_LIVE_TESTS=1`` and the provider key is set. Run with::

    TRACEGRADE_RUN_LIVE_TESTS=1 uv run pytest tests/live -m live -v

Optional: ``TRACEGRADE_LIVE_<PROVIDER>_MODEL`` and ``TRACEGRADE_LIVE_<PROVIDER>_JUDGE_MODEL``
override the agent and judge models (defaults: the provider's defaults).
These tests assert that the integration *works* (calls succeed, scores are valid), not
that the model is good: model behaviour is what the evaluations themselves measure.
"""

from __future__ import annotations

import os

import pytest

from tests.conftest import LIVE
from tracegrade.config import load_settings
from tracegrade.evaluation.dataset import load_bundled_dataset
from tracegrade.evaluation.engine import EvaluationEngine, RunRequest
from tracegrade.evaluation.metrics import SUITES
from tracegrade.evaluation.models import ExecutionStatus, MetricStatus, RunStatus
from tracegrade.evaluation.storage import RunStore
from tracegrade.providers.registry import PROVIDERS, ModelSpec, check_connection

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not LIVE, reason="set TRACEGRADE_RUN_LIVE_TESTS=1"),
]

CASES = ["refund-two-eligible-items", "unknown-customer", "quote-without-ticket"]


def spec(provider: str) -> ModelSpec:
    model = (
        os.environ.get(f"TRACEGRADE_LIVE_{provider.upper()}_MODEL")
        or PROVIDERS[provider].default_agent_model
    )
    return ModelSpec(
        provider=provider, model=model, temperature=0.0, timeout_seconds=180, max_retries=3
    )


@pytest.mark.parametrize("provider", ["groq", "openai"])
def test_live_agent_and_judge(provider: str, live_keys: dict[str, str]) -> None:
    key_name = PROVIDERS[provider].api_key_env
    if key_name not in live_keys:
        pytest.skip(f"{key_name} not set")
    settings = load_settings()
    model = spec(provider)
    judge = model.model_copy(
        update={
            "model": os.environ.get(f"TRACEGRADE_LIVE_{provider.upper()}_JUDGE_MODEL")
            or PROVIDERS[provider].default_judge_model
        }
    )
    assert "replied" in check_connection(model, settings)

    engine = EvaluationEngine(settings, RunStore(settings.runs_dir))
    record = engine.run_sync(
        RunRequest(
            dataset=load_bundled_dataset(),
            case_ids=CASES,
            agent=model,
            judge=judge,
            metric_ids=SUITES["all"],
            max_concurrency=1,
            label=f"live-test-{provider}",
        )
    )
    assert record.status is RunStatus.COMPLETED
    for case in record.cases:
        assert case.execution.status is ExecutionStatus.COMPLETED, case.execution.error
        assert case.execution.answer
        for outcome in case.metrics:
            assert outcome.status is not MetricStatus.ERROR, (outcome.metric_id, outcome.error)
            if outcome.score is not None:
                assert 0.0 <= outcome.score <= 1.0
    judge_scored = [
        m
        for c in record.cases
        for m in c.metrics
        if m.kind.value == "llm_judge" and m.score is not None
    ]
    assert judge_scored, "the judge produced no scores"

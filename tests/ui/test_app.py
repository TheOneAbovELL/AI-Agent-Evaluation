"""UI workflow tests: the real Streamlit pages driven headlessly with AppTest."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import tracegrade.ui as ui_package
from tracegrade.config import load_settings
from tracegrade.evaluation.dataset import load_bundled_dataset
from tracegrade.evaluation.engine import EvaluationEngine, RunRequest
from tracegrade.evaluation.metrics import NO_JUDGE_SUITE
from tracegrade.evaluation.storage import RunStore
from tracegrade.providers.registry import ModelSpec

pytestmark = pytest.mark.ui

APP = str(Path(ui_package.__file__).parent / "app.py")
TIMEOUT = 120


def text_of(at: AppTest) -> str:
    parts = []
    for kind in (
        "markdown",
        "caption",
        "info",
        "warning",
        "error",
        "success",
        "title",
        "subheader",
    ):
        parts.extend(str(getattr(e, "value", "")) for e in getattr(at, kind))
    return "\n".join(parts)


def open_page(page: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    if page != "home":
        at.switch_page(f"pages/{page}.py")
        at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def seed_runs(count: int = 2) -> list[str]:
    settings = load_settings()
    engine = EvaluationEngine(settings, RunStore(settings.runs_dir))
    ids = []
    for variant in ["reference", "naive"][:count]:
        record = engine.run_sync(
            RunRequest(
                dataset=load_bundled_dataset(),
                agent=ModelSpec(provider="offline", model=variant),
                metric_ids=NO_JUDGE_SUITE,
                case_ids=["refund-two-eligible-items", "mixed-eligibility"],
            )
        )
        ids.append(record.run_id)
    return ids


def test_home_without_runs() -> None:
    at = open_page("home")
    content = text_of(at)
    assert "No runs yet" in content and "Provider status" in content
    assert "GROQ_API_KEY is not set." in content


def test_home_with_runs_shows_latest() -> None:
    seed_runs(1)
    content = text_of(open_page("home"))
    assert "Latest:" in content and "Recent runs" in content


def test_evaluate_page_runs_an_offline_evaluation() -> None:
    at = open_page("evaluate")
    content = text_of(at)
    assert "rule-based" in content and "will be reported as skipped" not in content
    at.multiselect[0].set_value(["refund-two-eligible-items", "missing-customer-id"]).run()
    at.text_input[0].set_value("ui test run").run()
    run_button = next(b for b in at.button if b.label == "Run evaluation")
    assert not run_button.disabled
    run_button.click().run()
    assert not at.exception, [e.value for e in at.exception]
    content = text_of(at)
    assert "completed: 2 passed" in content
    runs = RunStore(load_settings().runs_dir).list_runs()
    assert len(runs) == 1 and runs[0].config.label == "ui test run"


def test_evaluate_page_blocks_unconfigured_provider() -> None:
    at = open_page("evaluate")
    at.selectbox[1].set_value("groq").run()
    content = text_of(at)
    assert "GROQ_API_KEY is not set" in content
    run_button = next(b for b in at.button if b.label == "Run evaluation")
    assert run_button.disabled


def test_results_page_shows_run_and_case_details() -> None:
    seed_runs(1)
    at = open_page("results")
    content = text_of(at)
    assert "Offline reference model" in content and "Metrics" in content
    assert "Hi, this is customer C1001. Please refund my laptop stand and my desk mat." in content
    assert "\\$54.00" in content  # dollar signs are escaped for markdown
    assert len(at.tabs) >= 4


def test_compare_page() -> None:
    seed_runs(2)
    at = open_page("compare")
    content = text_of(at)
    assert "Metric changes" in content and "Per-case changes" in content
    assert not at.exception


def test_compare_page_needs_two_runs() -> None:
    assert "at least two runs" in text_of(open_page("compare"))


def test_playground_chat_with_offline_agent() -> None:
    at = open_page("playground")
    at.chat_input[0].set_value("I'm C1004. Please refund only the screen protector.").run()
    assert not at.exception, [e.value for e in at.exception]
    content = text_of(at)
    assert "\\$8.00" in content and "TKT-0001" in content


def test_datasets_page() -> None:
    at = open_page("datasets")
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Cases"] == "16" and metrics["Reference date"] == "2026-11-20"
    assert "Synthetic refund-desk scenarios" in text_of(at)
    # the policy oracle table for the selected case is rendered
    assert any("Decision" in df.value.columns for df in at.dataframe)


def test_settings_page_never_shows_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "gsk_" + "s" * 40
    monkeypatch.setenv("GROQ_API_KEY", secret)
    at = open_page("settings_help")
    assert secret not in text_of(at)
    for df in at.dataframe:
        assert secret not in df.value.to_string()

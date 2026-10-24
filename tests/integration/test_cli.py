"""CLI behaviour, exercised in-process through ``tracegrade.cli.main``."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tracegrade.cli import main


def run_cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def latest_run_id(runs_dir: Path) -> str:
    return sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)[-1].stem


def test_doctor_metrics_and_dataset_commands(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run_cli(capsys, "doctor")
    assert code == 0 and "offline  Ready" in out and "GROQ_API_KEY is not set" in out
    code, out, _ = run_cli(capsys, "metrics")
    assert code == 0 and "refund_outcome" in out and "answer_correctness" in out
    code, out, _ = run_cli(capsys, "dataset", "list")
    assert "bundled:refund_support_v1" in out
    code, out, _ = run_cli(capsys, "dataset", "show")
    assert code == 0 and "16 case(s)" in out and "policy-override-attempt" in out


def test_dataset_validate_reports_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"name": "x"}', encoding="utf-8")
    code, _, err = run_cli(capsys, "dataset", "validate", str(bad))
    assert code == 2 and "failed validation" in err and "hint:" in err


def test_full_cli_workflow(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run_cli(
        capsys, "evaluate", "--suite", "deterministic", "--label", "base", "--quiet"
    )
    assert code == 0 and "passed 16" in out and "offline rule-based reference model" in out
    base = latest_run_id(tmp_path / "runs")

    code, out, _ = run_cli(
        capsys,
        "evaluate",
        "--agent-model",
        "naive",
        "--policy-mode",
        "prompt_only",
        "--metrics",
        "refund_outcome,tool_order",
        "--fail-on-failure",
        "--threshold",
        "tool_order=0.5",
    )
    assert code == 1 and "failed: refund_outcome" in out
    cand = latest_run_id(tmp_path / "runs")

    code, out, _ = run_cli(capsys, "runs", "list")
    assert code == 0 and base in out and cand in out
    code, out, _ = run_cli(capsys, "runs", "show", cand)
    assert "refund_outcome: failed" in out
    code, out, _ = run_cli(capsys, "runs", "compare", base, cand)
    assert code == 0 and "Different policy modes" in out and "Regressions:" in out
    for fmt in ("json", "csv", "cases-csv", "md"):
        target = tmp_path / f"export.{fmt}"
        code, _, _ = run_cli(
            capsys, "runs", "export", base, "--format", fmt, "--output", str(target)
        )
        assert code == 0 and target.stat().st_size > 0
    assert json.loads((tmp_path / "export.json").read_text(encoding="utf-8"))["run_id"] == base

    code, _, err = run_cli(capsys, "runs", "delete", cand)
    assert code == 2 and "--yes" in err
    code, _, _ = run_cli(capsys, "runs", "delete", cand, "--yes")
    assert code == 0 and not (tmp_path / "runs" / f"{cand}.json").exists()


def test_cli_errors_are_readable(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _, err = run_cli(capsys, "evaluate", "--metrics", "nonsense")
    assert code == 2 and "Unknown metric" in err
    code, _, err = run_cli(capsys, "evaluate", "--agent-provider", "groq", "--quiet")
    assert code == 2 and "GROQ_API_KEY" in err
    code, _, err = run_cli(capsys, "runs", "show", "../../secrets")
    assert code == 2 and "Invalid run id" in err
    monkeypatch.setenv("TRACEGRADE_AGENT_PROVIDER", "bard")
    code, _, err = run_cli(capsys, "doctor")
    assert code == 2 and "TRACEGRADE_AGENT_PROVIDER" in err


def test_module_entry_point_runs_in_subprocess(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tracegrade", "--version"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0 and result.stdout.startswith("tracegrade ")

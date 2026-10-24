"""Command-line interface: ``tracegrade <command>``.

Exit codes: 0 success; 1 evaluation finished with failures (only with
``--fail-on-failure``) or the run did not complete; 2 configuration/usage error;
130 interrupted by the user.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from tracegrade import __version__
from tracegrade.config import PolicyMode, Settings, load_settings
from tracegrade.errors import TraceGradeError
from tracegrade.logging_utils import configure_logging

DEFAULT_DATASET = "bundled:refund_support_v1"


# ------------------------------------------------------------------------ helpers --
def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    cells = [[str(h) for h in headers]] + [["" if v is None else str(v) for v in r] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    if getattr(args, "env_file", None):
        overrides["_env_file"] = args.env_file
    return load_settings(**overrides)


def _store(settings: Settings) -> Any:
    from tracegrade.evaluation.storage import RunStore

    return RunStore(settings.runs_dir)


# ------------------------------------------------------------------------ commands --
def cmd_evaluate(args: argparse.Namespace, settings: Settings) -> int:
    from tracegrade.evaluation.dataset import resolve_dataset
    from tracegrade.evaluation.engine import EngineEvent, EvaluationEngine, RunRequest
    from tracegrade.evaluation.metrics import resolve_metric_ids
    from tracegrade.providers.registry import (
        PROVIDERS,
        ModelSpec,
        default_agent_spec,
        default_judge_spec,
    )

    dataset = resolve_dataset(args.dataset, settings.max_upload_bytes)
    agent = default_agent_spec(settings)
    if args.agent_provider:
        agent.provider = args.agent_provider
        if not args.agent_model:
            agent.model = PROVIDERS[args.agent_provider].default_agent_model
    if args.agent_model:
        agent.model = args.agent_model
    judge = default_judge_spec(settings)
    if args.judge_provider:
        if args.judge_provider == "none":
            judge = None
        else:
            judge = ModelSpec(
                provider=args.judge_provider,
                model=args.judge_model or PROVIDERS[args.judge_provider].default_judge_model or "",
                temperature=0.0,
                timeout_seconds=settings.judge_timeout_seconds,
                max_retries=settings.judge_max_retries,
            )
    elif args.judge_model and judge is not None:
        judge.model = args.judge_model

    thresholds: dict[str, float] = {}
    for item in args.threshold or []:
        key, _, value = item.partition("=")
        try:
            thresholds[key.strip()] = float(value)
        except ValueError:
            raise TraceGradeError(f"Invalid --threshold '{item}'; use metric_id=0.8") from None

    request = RunRequest(
        dataset=dataset,
        case_ids=[c.strip() for c in args.cases.split(",")] if args.cases else None,
        agent=agent,
        judge=judge,
        metric_ids=resolve_metric_ids(
            [m.strip() for m in args.metrics.split(",")] if args.metrics else None, args.suite
        ),
        thresholds=thresholds,
        policy_mode=PolicyMode(args.policy_mode or settings.policy_mode),
        max_concurrency=args.concurrency or settings.max_concurrency,
        recursion_limit=settings.agent_recursion_limit,
        label=args.label,
    )
    engine = EvaluationEngine(settings, _store(settings))
    preflight = engine.preflight(request)
    for line in preflight.info:
        print(f"info: {line}")
    for line in preflight.warnings:
        print(f"warning: {line}")
    if not preflight.ok:
        for line in preflight.errors:
            print(f"error: {line}", file=sys.stderr)
        return 2

    def on_event(event: EngineEvent) -> None:
        if args.quiet:
            return
        if event.kind == "run_started":
            print(
                f"Run {event.record.run_id}: {event.total} case(s), agent "
                f"{request.agent.label}, judge {request.judge.label if request.judge else 'none'}"
            )
        elif event.kind == "case_finished" and event.case_result is not None:
            r = event.case_result
            failed = [m.metric_id for m in r.metrics if m.status.value == "failed"]
            extra = f" failed: {', '.join(failed)}" if failed else ""
            if r.execution.error:
                extra = f" agent error: {r.execution.error[:120]}"
            print(
                f"  [{event.completed}/{event.total}] {r.case_id:<32} {r.status.value:<10}{extra}"
            )

    record = asyncio.run(engine.run(request, on_event=on_event))
    _print_summary(record)
    print(f"\nSaved to {settings.runs_dir / (record.run_id + '.json')}")
    if record.status.value != "completed":
        return 1
    if args.fail_on_failure and (record.summary.failed or record.summary.errors):
        return 1
    return 0


def _print_summary(record: Any) -> None:
    s = record.summary
    print(f"\nRun {record.run_id} - {record.status.value}")
    if record.is_offline:
        print("Agent: offline rule-based reference model (not an LLM).")
    print(
        f"Cases: {s.finished_cases}/{s.total_cases} finished | passed {s.passed} | failed "
        f"{s.failed} | incomplete {s.incomplete} | agent errors {s.errors} | "
        f"case pass rate {_pct(s.case_pass_rate)}"
    )
    rows = [
        [
            m.metric_id,
            m.kind.value,
            f"{m.threshold:.2f}",
            _num(m.mean_score),
            _pct(m.pass_rate),
            f"{m.passed}/{m.evaluated}",
            m.errors,
            m.skipped,
        ]
        for m in s.metrics
    ]
    print(_table(["metric", "kind", "thr", "mean", "pass rate", "passed", "err", "skip"], rows))


def cmd_resume(args: argparse.Namespace, settings: Settings) -> int:
    from tracegrade.evaluation.engine import EvaluationEngine

    engine = EvaluationEngine(settings, _store(settings))
    record = asyncio.run(engine.resume(args.run_id, retry_errors=args.retry_errors))
    _print_summary(record)
    return 0 if record.status.value == "completed" else 1


def cmd_runs(args: argparse.Namespace, settings: Settings) -> int:
    store = _store(settings)
    if args.runs_command == "list":
        runs = store.list_runs()[: args.limit]
        if not runs:
            print(f"No runs in {settings.runs_dir}.")
            return 0
        rows = [
            [
                r.run_id,
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                r.status.value,
                r.config.agent.label,
                r.config.judge.label if r.config.judge else "none",
                f"{r.summary.passed}/{r.summary.finished_cases}",
                r.config.label or "",
            ]
            for r in runs
        ]
        print(_table(["run id", "created", "status", "agent", "judge", "passed", "label"], rows))
        return 0
    if args.runs_command == "show":
        record = store.load(args.run_id)
        _print_summary(record)
        for case in record.cases:
            print(f"\n- {case.case_id}: {case.status.value}")
            print(f"  answer: {case.execution.answer}")
            for m in case.metrics:
                if m.status.value in ("failed", "error"):
                    detail = (m.reason or m.error or "").strip()[:300]
                    print(f"  {m.metric_id}: {m.status.value} - {detail}")
        return 0
    if args.runs_command == "export":
        from tracegrade.evaluation.export import export

        content, filename, _ = export(store.load(args.run_id), args.format)
        output = Path(args.output) if args.output else Path(filename)
        output.write_text(content, encoding="utf-8")
        print(f"Wrote {output}")
        return 0
    if args.runs_command == "compare":
        from tracegrade.evaluation.compare import compare_runs

        result = compare_runs(store.load(args.baseline), store.load(args.candidate))
        for warning in result.warnings:
            print(f"warning: {warning}")
        rows = [
            [
                d.metric_id,
                _num(d.baseline_mean),
                _num(d.candidate_mean),
                "n/a" if d.mean_delta is None else f"{d.mean_delta:+.3f}",
                _pct(d.baseline_pass_rate),
                _pct(d.candidate_pass_rate),
            ]
            for d in result.metrics
        ]
        print(_table(["metric", "base mean", "cand mean", "delta", "base pass", "cand pass"], rows))
        print(f"\nRegressions: {', '.join(c.case_id for c in result.regressions) or 'none'}")
        print(f"Improvements: {', '.join(c.case_id for c in result.improvements) or 'none'}")
        return 0
    if args.runs_command == "delete":
        if not args.yes:
            print("Refusing to delete without --yes.", file=sys.stderr)
            return 2
        store.delete(args.run_id)
        print(f"Deleted run {args.run_id}.")
        return 0
    return 2


def cmd_dataset(args: argparse.Namespace, settings: Settings) -> int:
    from tracegrade.evaluation.dataset import bundled_dataset_names, resolve_dataset

    if args.dataset_command == "list":
        for name in bundled_dataset_names():
            print(f"bundled:{name}")
        if settings.datasets_dir.exists():
            for path in sorted(settings.datasets_dir.glob("*.json")):
                print(path)
        return 0
    loaded = resolve_dataset(args.spec, settings.max_upload_bytes)
    ds = loaded.dataset
    print(
        f"OK: '{ds.name}' - {len(ds.cases)} case(s), {len(ds.customers)} customer(s), "
        f"reference date {ds.reference_date}, sha256 {loaded.sha256[:12]}"
    )
    for warning in ds.warnings():
        print(f"warning: {warning}")
    if args.dataset_command == "show":
        rows = [
            [
                c.id,
                c.expected_refund_total,
                ",".join(t.name for t in c.expected_tools),
                c.input[:60],
            ]
            for c in ds.cases
        ]
        print(_table(["case", "refund", "expected tools", "input"], rows))
    return 0


def cmd_metrics(args: argparse.Namespace, settings: Settings) -> int:
    from tracegrade.evaluation.metrics import METRICS

    rows = [
        [
            d.id,
            d.kind.value,
            f"{d.default_threshold:.2f}",
            "yes" if d.requires_judge else "no",
            d.description,
        ]
        for d in METRICS.values()
    ]
    print(_table(["metric", "kind", "threshold", "judge", "description"], rows))
    return 0


def cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    from tracegrade.evaluation.engine import environment_info
    from tracegrade.providers.registry import (
        check_connection,
        default_agent_spec,
        default_judge_spec,
        provider_status,
    )

    print(f"TraceGrade {__version__}")
    for key, value in environment_info().items():
        print(f"  {key}: {value}")
    print("\nConfiguration")
    agent = default_agent_spec(settings)
    judge = default_judge_spec(settings)
    print(f"  agent: {agent.label}  policy mode: {settings.policy_mode.value}")
    print(f"  judge: {judge.label if judge else 'none'}")
    print(f"  runs dir: {settings.runs_dir.resolve()}")
    print("\nProviders")
    for status in provider_status(settings):
        mark = "ok " if status.usable else "-- "
        print(f"  {mark}{status.name:<8} {status.message}")
    code = 0
    if args.ping:
        print("\nConnection checks (makes real API calls)")
        for spec in [agent] + ([judge] if judge else []):
            try:
                print(f"  {check_connection(spec, settings)}")
            except Exception as exc:
                print(f"  FAILED {spec.label}: {type(exc).__name__}: {str(exc)[:200]}")
                code = 1
    return code


def cmd_chat(args: argparse.Namespace, settings: Settings) -> int:
    from langgraph.checkpoint.memory import InMemorySaver

    from tracegrade.evaluation.dataset import resolve_dataset
    from tracegrade.evaluation.execution import extract_tool_calls
    from tracegrade.providers.registry import PROVIDERS, build_chat_model, default_agent_spec
    from tracegrade.refund.agent import build_refund_agent
    from tracegrade.refund.tools import RefundToolContext

    loaded = resolve_dataset(args.dataset, settings.max_upload_bytes)
    spec = default_agent_spec(settings)
    if args.provider:
        spec.provider = args.provider
        spec.model = args.model or PROVIDERS[args.provider].default_agent_model
    elif args.model:
        spec.model = args.model
    today = date.today() if args.real_date else loaded.dataset.reference_date
    context = RefundToolContext(
        records=loaded.dataset.records(),
        reference_date=today,
        policy_mode=PolicyMode(args.policy_mode or settings.policy_mode),
        window_days=loaded.dataset.refund_window_days,
    )
    agent = build_refund_agent(
        build_chat_model(spec, settings),
        context,
        checkpointer=InMemorySaver(),
        model_retries=0 if spec.provider == "offline" else spec.max_retries,
    )
    config = {
        "configurable": {"thread_id": f"chat-{uuid4().hex}"},
        "recursion_limit": settings.agent_recursion_limit,
    }
    print(
        f"Refund agent chat ({spec.label}, today = {today}). Sample customers: "
        f"{', '.join(loaded.dataset.records().customer_ids()[:5])} ... Type 'exit' to quit."
    )
    seen = 0
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in {"exit", "quit"}:
            break
        if not text:
            continue
        result = agent.invoke({"messages": [{"role": "user", "content": text}]}, config=config)
        calls = extract_tool_calls(result["messages"])
        for call in calls[seen:]:
            print(f"  [tool] {call.name}({json.dumps(call.args)})")
        seen = len(calls)
        answer = result.get("structured_response")
        print(f"agent> {answer.message if answer else result['messages'][-1].content}")
        if answer is not None and not answer.awaiting_customer:
            print("(the agent considers this request resolved)")
    for ticket in context.ledger.tickets:
        print(f"Ticket {ticket.ticket_id}: {ticket.customer_id} ${ticket.amount}")
    return 0


def cmd_ui(args: argparse.Namespace, settings: Settings) -> int:
    app = Path(__file__).parent / "ui" / "app.py"
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.port",
        str(args.port),
        "--server.headless",
        str(args.headless).lower(),
        "--browser.gatherUsageStats",
        "false",
    ]
    return subprocess.call(command)  # noqa: S603 - fixed argv, no shell


# ------------------------------------------------------------------------ parser --
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tracegrade",
        description="Evaluate a tool-using LangChain agent with deterministic checks and "
        "DeepEval LLM-as-a-judge metrics.",
    )
    parser.add_argument("--version", action="version", version=f"tracegrade {__version__}")
    parser.add_argument("--env-file", help="Load settings from this .env file (default: ./.env)")
    sub = parser.add_subparsers(dest="command", required=True)

    ev = sub.add_parser("evaluate", help="Run an evaluation")
    ev.add_argument("--dataset", default=DEFAULT_DATASET, help="bundled:<name> or a JSON file path")
    ev.add_argument("--cases", help="Comma-separated case ids (default: all)")
    ev.add_argument("--agent-provider", choices=["offline", "openai", "groq"])
    ev.add_argument("--agent-model")
    ev.add_argument("--judge-provider", choices=["none", "openai", "groq"])
    ev.add_argument("--judge-model")
    group = ev.add_mutually_exclusive_group()
    group.add_argument("--metrics", help="Comma-separated metric ids (see `tracegrade metrics`)")
    group.add_argument("--suite", choices=["deterministic", "judge", "all"], default=None)
    ev.add_argument("--threshold", action="append", metavar="METRIC=VALUE")
    ev.add_argument("--policy-mode", choices=[m.value for m in PolicyMode])
    ev.add_argument("--concurrency", type=int)
    ev.add_argument("--label", help="Free-text label stored with the run")
    ev.add_argument(
        "--fail-on-failure",
        action="store_true",
        help="Exit 1 if any case failed or errored (for CI)",
    )
    ev.add_argument("--quiet", action="store_true")
    ev.set_defaults(func=cmd_evaluate)

    rs = sub.add_parser("resume", help="Finish an interrupted run")
    rs.add_argument("run_id")
    rs.add_argument(
        "--retry-errors", action="store_true", help="Also re-run cases whose agent errored"
    )
    rs.set_defaults(func=cmd_resume)

    runs = sub.add_parser("runs", help="Inspect stored runs")
    runs_sub = runs.add_subparsers(dest="runs_command", required=True)
    rl = runs_sub.add_parser("list")
    rl.add_argument("--limit", type=int, default=20)
    runs_sub.add_parser("show").add_argument("run_id")
    rx = runs_sub.add_parser("export")
    rx.add_argument("run_id")
    rx.add_argument("--format", choices=["json", "csv", "cases-csv", "md"], default="json")
    rx.add_argument("--output")
    rc = runs_sub.add_parser("compare")
    rc.add_argument("baseline")
    rc.add_argument("candidate")
    rd = runs_sub.add_parser("delete")
    rd.add_argument("run_id")
    rd.add_argument("--yes", action="store_true")
    runs.set_defaults(func=cmd_runs)

    ds = sub.add_parser("dataset", help="List, validate or show datasets")
    ds_sub = ds.add_subparsers(dest="dataset_command", required=True)
    ds_sub.add_parser("list")
    ds_sub.add_parser("validate").add_argument("spec")
    ds_sub.add_parser("show").add_argument("spec", nargs="?", default=DEFAULT_DATASET)
    ds.set_defaults(func=cmd_dataset)

    sub.add_parser("metrics", help="List available metrics").set_defaults(func=cmd_metrics)

    dr = sub.add_parser("doctor", help="Show configuration and provider status")
    dr.add_argument(
        "--ping", action="store_true", help="Make one tiny real API call per configured model"
    )
    dr.set_defaults(func=cmd_doctor)

    ch = sub.add_parser("chat", help="Chat with the refund agent in the terminal")
    ch.add_argument("--provider", choices=["offline", "openai", "groq"])
    ch.add_argument("--model")
    ch.add_argument("--dataset", default=DEFAULT_DATASET, help="Customer data source")
    ch.add_argument("--policy-mode", choices=[m.value for m in PolicyMode])
    ch.add_argument(
        "--real-date",
        action="store_true",
        help="Use the machine's date instead of the dataset reference date",
    )
    ch.set_defaults(func=cmd_chat)

    ui = sub.add_parser("ui", help="Launch the Streamlit web interface")
    ui.add_argument("--port", type=int, default=8501)
    ui.add_argument("--headless", action="store_true")
    ui.set_defaults(func=cmd_ui)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = _settings(args)
        secrets = [
            k.get_secret_value() for k in (settings.openai_api_key, settings.groq_api_key) if k
        ]
        configure_logging(
            "WARNING" if getattr(args, "quiet", False) else settings.log_level,
            settings.log_format,
            settings.log_file,
            secrets,
        )
        return int(args.func(args, settings))
    except TraceGradeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "\nInterrupted. Completed cases were saved; use `tracegrade resume <run_id>`.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

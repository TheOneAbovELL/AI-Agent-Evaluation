# Part XII — Reference material

## 77. Configuration and environment-variable reference

All variables are optional. Source: `src/tracegrade/config.py`.

| Variable | Type / allowed | Default | Effect |
|---|---|---|---|
| `TRACEGRADE_AGENT_PROVIDER` | `offline` \| `openai` \| `groq` | `offline` | Agent provider |
| `TRACEGRADE_AGENT_MODEL` | string; blank = provider default | `reference` / `gpt-5.4` / `openai/gpt-oss-120b` | Agent model or offline variant (`reference`, `naive`) |
| `TRACEGRADE_AGENT_TEMPERATURE` | 0–2 or blank | `0.0` | Blank omits the parameter |
| `TRACEGRADE_AGENT_TIMEOUT_SECONDS` | (0, 3600] | `300` | Per-case agent timeout (also client timeout) |
| `TRACEGRADE_AGENT_MAX_RETRIES` | 0–10 | `4` | Client retries per model call and retry-middleware attempts |
| `TRACEGRADE_AGENT_RECURSION_LIMIT` | 5–200 | `25` | LangGraph step limit |
| `TRACEGRADE_POLICY_MODE` | `enforced` \| `prompt_only` | `enforced` | Tool guardrails |
| `TRACEGRADE_JUDGE_PROVIDER` | `none` \| `openai` \| `groq` | `none` | Judge provider |
| `TRACEGRADE_JUDGE_MODEL` | string; blank = provider default | `gpt-5.4` / `openai/gpt-oss-120b` | Judge model |
| `TRACEGRADE_JUDGE_TIMEOUT_SECONDS` | (0, 3600] | `180` | Per judge-metric attempt |
| `TRACEGRADE_JUDGE_MAX_RETRIES` | 0–10 | `4` | Retries of transient judge failures |
| `TRACEGRADE_MAX_CONCURRENCY` | 1–16 | `2` | Parallel cases (judge calls ≤ 3×) |
| `TRACEGRADE_RUNS_DIR` | path | `runs` | Run store |
| `TRACEGRADE_DATASETS_DIR` | path | `datasets` | UI-selectable datasets and uploads |
| `TRACEGRADE_MAX_UPLOAD_BYTES` | 1,000–50,000,000 | `1000000` | Dataset size limit |
| `TRACEGRADE_LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` | Logger level |
| `TRACEGRADE_LOG_FORMAT` | `text` \| `json` | `text` | Log format |
| `TRACEGRADE_LOG_FILE` | path | unset | Also log to this file |
| `OPENAI_API_KEY` | secret | unset | OpenAI credential |
| `GROQ_API_KEY` | secret | unset | Groq credential |
| `DEEPEVAL_TELEMETRY_OPT_OUT` | `1`/`0` | set to `1` if unset | DeepEval telemetry |
| `TRACEGRADE_RUN_LIVE_TESTS` | `1` | unset | Enables `tests/live` |
| `TRACEGRADE_LIVE_GROQ_MODEL`, `TRACEGRADE_LIVE_OPENAI_MODEL` | string | provider default | Model for live tests |

Streamlit options are in `.streamlit/config.toml` (theme, headless, upload size, usage stats
off, viewer toolbar).

## 78. CLI reference

| Command | Options | Purpose |
|---|---|---|
| `tracegrade evaluate` | `--dataset SPEC` (default `bundled:refund_support_v1`), `--cases a,b`, `--agent-provider`, `--agent-model`, `--judge-provider`, `--judge-model`, `--suite deterministic\|judge\|all` or `--metrics id,…`, `--threshold id=v` (repeatable), `--policy-mode`, `--concurrency N`, `--label`, `--fail-on-failure`, `--quiet` | Run an evaluation |
| `tracegrade resume RUN_ID` | `--retry-errors` | Finish an interrupted run |
| `tracegrade runs list` | `--limit N` (20) | List runs |
| `tracegrade runs show RUN_ID` | | Summary + failed/errored metrics per case |
| `tracegrade runs export RUN_ID` | `--format json\|csv\|cases-csv\|md`, `--output FILE` | Export |
| `tracegrade runs compare A B` | | Compare baseline A and candidate B |
| `tracegrade runs delete RUN_ID` | `--yes` (required) | Delete a run file |
| `tracegrade dataset list` | | Bundled datasets and files in the datasets folder |
| `tracegrade dataset validate SPEC` | | Validate a dataset |
| `tracegrade dataset show [SPEC]` | | Validate and list cases |
| `tracegrade metrics` | | Metric catalogue |
| `tracegrade doctor` | `--ping` | Versions, configuration, providers, optional connection check |
| `tracegrade chat` | `--provider`, `--model`, `--dataset`, `--policy-mode`, `--real-date` | Terminal conversation |
| `tracegrade ui` | `--port` (8501), `--headless` | Start the Streamlit UI |
| global | `--version`, `--env-file PATH` | |

Exit codes: 0 ok; 1 run not completed or failures with `--fail-on-failure`; 2 configuration,
dataset or usage error; 130 interrupted.

## 79. Python API reference (stable entry points)

```python
from tracegrade.config import load_settings, PolicyMode
from tracegrade.evaluation.dataset import load_bundled_dataset, load_dataset, resolve_dataset
from tracegrade.evaluation.engine import EvaluationEngine, RunRequest
from tracegrade.evaluation.metrics import SUITES, METRICS
from tracegrade.evaluation.storage import RunStore
from tracegrade.evaluation.export import export
from tracegrade.evaluation.compare import compare_runs
from tracegrade.providers.registry import ModelSpec

settings = load_settings()
engine = EvaluationEngine(settings, RunStore(settings.runs_dir))
request = RunRequest(
    dataset=load_bundled_dataset(),
    agent=ModelSpec(provider="offline", model="reference"),
    judge=None,
    metric_ids=SUITES["deterministic"],
    max_concurrency=4,
)
preflight = engine.preflight(request)      # .errors, .warnings, .info, .ok
record = engine.run_sync(request)          # RunRecord; or: await engine.run(request, on_event=...)
content, filename, mime = export(record, "md")
```

| Object | Key members |
|---|---|
| `EvaluationEngine` | `preflight`, `run`, `run_sync`, `resume`, `create_record`, `thresholds_for` |
| `RunRequest` | `dataset`, `case_ids`, `agent`, `judge`, `metric_ids`, `thresholds`, `policy_mode`, `max_concurrency`, `recursion_limit`, `label` |
| `EngineEvent` | `kind`, `record`, `case_id`, `case_result`, `completed`, `total` |
| `RunStore` | `save`, `load`, `exists`, `list_runs`, `delete` |
| `ModelSpec` | `provider`, `model`, `temperature`, `timeout_seconds`, `max_retries`, `label` |
| Refund agent | `refund.agent.build_refund_agent(model, RefundToolContext(...), checkpointer=None)` |
| Policy | `refund.policy.assess_refund(records, customer, items, reference_date, window)` |

## 80. Data schemas

### 80.1 Dataset (`schema_version` 1)

```text
EvalDataset
  schema_version: 1
  name: str (1-100)
  description: str = ""
  reference_date: date (YYYY-MM-DD)
  refund_window_days: int = 30 (0-3650)
  customers: {customer ID: {item: {price: decimal >= 0 (2 dp), date: date}}}
  cases: [EvalCase] (>= 1, unique ids)
EvalCase
  id: str  ^[a-z0-9][a-z0-9_-]{0,79}$
  input: str (1-4000)
  expected_output: str | null (<= 4000)
  expected_tools: [{name: str, input_parameters: object | null}]
  forbidden_tools: [str]            (disjoint from expected tool names)
  expected_refund_total: number >= 0 | null   (0 = no ticket, null = unchecked)
  customer: str | null; requested_items: [str] | null   (oracle metadata)
  tags: [str]; notes: str | null
Unknown fields are rejected.
```

### 80.2 Run record (`runs/<run_id>.json`, `schema_version` 1)

```text
RunRecord
  schema_version, run_id (YYYYMMDD-HHMMSS-xxxxxx), created_at, finished_at (UTC)
  status: running | completed | interrupted | failed
  error: str | null
  config: RunConfig
    dataset_name, dataset_source, dataset_sha256, reference_date, case_ids[]
    agent: ModelSpec; judge: ModelSpec | null
    metric_ids[], thresholds{metric_id: float}, policy_mode
    max_concurrency, agent_recursion_limit, prompt_fingerprint, label
  environment: {python, platform, tracegrade, deepeval, langchain, langchain-core,
                langgraph, langchain-openai, langchain-groq, pydantic}
  cases: [CaseResult]
    case_id, input, expected_output, expected_refund_total, tags[]
    status: passed | failed | incomplete | error; started_at, finished_at
    execution: AgentExecution
      status: completed | error | timeout; answer (reply text); conversation_continues
      structured_response: bool
      tool_calls: [{name, args, output, call_id}]
      tickets: [{ticket_id, customer_id, amount}]; rejected_tickets: [{customer_id, amount, reason}]
      trace: {name, type: agent, input, output, available_tools[], children: [span]}
        span (llm):  {name, type: llm, model, input: [message], output, token_usage?,
                      start_ms, duration_ms, error?}
        span (tool): {name, type: tool, input, output, start_ms, duration_ms, error?}
      latency_ms, input_tokens, output_tokens, error_type, error, warnings[]
    metrics: [MetricOutcome]
      metric_id, name, kind: deterministic | heuristic | llm_judge
      status: passed | failed | error | skipped; score (0-1 | null); threshold
      reason, error, duration_ms, attempts, evaluation_model, evaluation_cost
  summary: RunSummary
    total_cases, finished_cases, passed, failed, incomplete, errors
    metrics: [MetricSummary{metric_id, name, kind, threshold, evaluated, passed,
              failed, errors, skipped, mean_score, min_score, max_score}]
    total_tickets, total_refunded, agent_input_tokens, agent_output_tokens,
    judge_cost, mean_agent_latency_ms
```

### 80.3 Exports

* Metric CSV columns: `run_id, case_id, case_status, metric_id, metric_name, kind, status,
  score, threshold, reason, error, evaluation_model, duration_ms, attempts`.
* Case CSV columns: `run_id, case_id, status, input, answer, expected_refund_total,
  refunded_total, tickets, tools_called, execution_status, latency_ms, error,
  score:<metric_id>…`.

## 81. Metric reference (summary)

| id | Kind | τ | Needs judge | N/A when |
|---|---|---:|---|---|
| `refund_outcome` | deterministic | 1.0 | no | no `expected_refund_total` |
| `expected_tool_coverage` | deterministic | 1.0 | no | no expected tools |
| `forbidden_tool_avoidance` | deterministic | 1.0 | no | no forbidden tools |
| `tool_argument_match` | deterministic | 1.0 | no | no expected parameters |
| `tool_order` | deterministic | 1.0 | no | < 2 expected tools |
| `answer_action_consistency` | heuristic | 1.0 | no | no answer text |
| `deepeval_tool_correctness` | deterministic (DeepEval) | 0.9 | no | no expected tools |
| `task_completion` | LLM judge | 0.8 | yes | no trace |
| `step_efficiency` | LLM judge | 0.8 | yes | no trace |
| `plan_quality` | LLM judge | 0.8 | yes | no trace |
| `plan_adherence` | LLM judge | 0.8 | yes | no trace |
| `argument_correctness` | LLM judge | 0.9 | yes | no tool calls |
| `answer_correctness` | LLM judge | 0.8 | yes | no `expected_output` |

All metrics are skipped for a case whose agent execution did not complete. Formulas: Chapter 30.

## 82. Error and troubleshooting reference

| Message (excerpt) | Meaning | Action |
|---|---|---|
| `Invalid configuration: TRACEGRADE_X: …` | Bad setting value | Fix `.env` |
| `Provider 'groq' needs GROQ_API_KEY, which is not set.` | Missing key | Add key |
| `Provider 'p' needs the Python package 'langchain_groq'.` | Incomplete install | `uv sync` |
| `Offline model must be one of reference, naive` | Wrong offline variant | Fix model |
| `Dataset '…' is not valid JSON (line L, column C: …)` | Syntax error | Fix file |
| `Dataset '…' failed validation: cases.0.id: …` | Schema error | Fix field |
| `Dataset '…' is N bytes; the limit is M bytes.` | Too large | Split or raise limit |
| `Dataset '…' has no case 'x'.` | Unknown case id | Check ids |
| `Run cannot start: …` | Preflight errors | Read the listed errors |
| `Agent did not finish within N seconds.` | Timeout | Raise timeout / check provider |
| `Agent exceeded the recursion limit of N steps` | Tool loop | Inspect trace |
| `Judge did not respond within N seconds.` | Judge timeout | Raise judge timeout |
| `Judge returned an invalid score: …` | Malformed judge output | Different judge model |
| `No judge model configured for this run.` | Skipped judge metric | Configure a judge |
| `Not evaluated: agent execution error/timeout.` | Metrics skipped | Fix the agent error |
| `Dataset … changed since run … started` | Resume refused | Start a new run |
| `Invalid run id` | Malformed id | Use an id from `runs list` |
| `Run file … is corrupt or from an unsupported version` | Corrupt JSON | Restore from backup or delete |
| `Refusing to delete without --yes.` | Safety | Add `--yes` |

## 83. Dependency inventory

Direct runtime dependencies (installed versions at verification): `langchain` 1.4.7,
`langchain-core` 1.7.0, `langgraph` 1.2.16, `langchain-openai` 1.7.2, `langchain-groq` 1.1.3,
`deepeval` 4.3.1, `pydantic` 2.14.1, `pydantic-settings` 2.16.1, `python-dotenv` 1.2.4,
`streamlit` 1.66.1, `pandas` 3.1.0, `altair` 6.3.0. Notable transitive: `openai` 3.37.0,
`groq` 0.37.1, `httpx` 0.28.1, `tenacity` 9.2.1, `numpy` 2.5.4, `pyarrow` 26.0.0. Dev group:
`pytest` 9.1.1, `pytest-cov` 7.1.0, `ruff` 0.17.2, `mypy` 2.4.0, `bandit` 1.9.4, `pip-audit`
2.10.1. Docs group: `markdown` 3.11.2, `pygments` 2.21.0, `python-docx` 1.2.0. In total 147
packages are installed in the development environment; `uv.lock` pins all of them.

## 84. Glossary

| Term | Meaning |
|---|---|
| Agent | The LangChain `create_agent` graph under test |
| Case | One dataset scenario (customer message + expectations) |
| Execution | One agent run for one case (`AgentExecution`) |
| Ledger | Per-session record of quotes, tickets and rejected tickets kept by the tools |
| Guardrail | Tool-side validation in `enforced` mode |
| Reference date | The date the agent sees as "today", from the dataset |
| Oracle | The deterministic policy used to check dataset expectations |
| Offline model | Rule-based stand-in for an LLM (`reference`, `naive`) |
| Judge | LLM that scores agent behaviour for DeepEval metrics |
| Trace | Span tree of model and tool calls recorded during an execution |
| Threshold (τ) | Minimum score for a metric to pass |
| Skipped | Metric not applicable or prerequisite missing; not a pass |
| Error (metric) | Metric applied but could not be computed |
| Incomplete (case) | No failed metric but at least one error, or nothing evaluated |
| Preflight | Validation of a run request before anything executes |
| Run record | Persisted JSON result of a run |

## 85. Source-file index

| File | Lines | Purpose |
|---|---:|---|
| `src/tracegrade/__init__.py` | 1 | Version |
| `src/tracegrade/__main__.py` | 3 | `python -m tracegrade` |
| `src/tracegrade/cli.py` | 544 | CLI (Ch. 24) |
| `src/tracegrade/config.py` | 156 | Settings (Ch. 20.1) |
| `src/tracegrade/errors.py` | 44 | Exceptions (Ch. 20.2) |
| `src/tracegrade/logging_utils.py` | 114 | Logging, redaction (Ch. 20.3) |
| `src/tracegrade/refund/records.py` | 93 | Purchase records (Ch. 21.1) |
| `src/tracegrade/refund/policy.py` | 144 | Policy (Ch. 21.2) |
| `src/tracegrade/refund/schemas.py` | 34 | AgentReply, PurchaseItem (Ch. 21.3) |
| `src/tracegrade/refund/prompts.py` | 56 | System prompt (Ch. 21.3) |
| `src/tracegrade/refund/tools.py` | 251 | Tools, ledger (Ch. 21.4) |
| `src/tracegrade/refund/agent.py` | 91 | Agent assembly (Ch. 21.5) |
| `src/tracegrade/providers/registry.py` | 256 | Providers (Ch. 22.1) |
| `src/tracegrade/providers/offline.py` | 370 | Offline model (Ch. 22.2) |
| `src/tracegrade/providers/judge_adapter.py` | 91 | Judge adapter (Ch. 22.3) |
| `src/tracegrade/evaluation/dataset.py` | 208 | Datasets (Ch. 23.1) |
| `src/tracegrade/evaluation/models.py` | 212 | Result schema (Ch. 23.2) |
| `src/tracegrade/evaluation/tracing.py` | 198 | Trace recorder (Ch. 23.3) |
| `src/tracegrade/evaluation/execution.py` | 170 | Case execution (Ch. 23.4) |
| `src/tracegrade/evaluation/metrics/base.py` | 32 | Metric types (Ch. 23.5) |
| `src/tracegrade/evaluation/metrics/deterministic.py` | 275 | Deterministic metrics (Ch. 23.5, 30) |
| `src/tracegrade/evaluation/metrics/judge.py` | 359 | DeepEval metrics (Ch. 23.5, 30) |
| `src/tracegrade/evaluation/metrics/__init__.py` | 94 | Catalogue, suites (Ch. 23.5) |
| `src/tracegrade/evaluation/engine.py` | 473 | Orchestration (Ch. 23.6) |
| `src/tracegrade/evaluation/aggregate.py` | 105 | Aggregation (Ch. 23.7, 31) |
| `src/tracegrade/evaluation/storage.py` | 115 | Run store (Ch. 23.7) |
| `src/tracegrade/evaluation/export.py` | 195 | Exports (Ch. 23.7) |
| `src/tracegrade/evaluation/compare.py` | 129 | Comparison (Ch. 23.7) |
| `src/tracegrade/resources/datasets/refund_support_v1.json` | 274 | Bundled dataset (Ch. 28) |
| `src/tracegrade/ui/app.py` | 68 | UI entry (Ch. 25, 36) |
| `src/tracegrade/ui/state.py` | 88 | UI state (Ch. 25) |
| `src/tracegrade/ui/components.py` | 390 | UI components (Ch. 25) |
| `src/tracegrade/ui/pages/*.py` | 87–321 each | Pages (Ch. 36) |
| `tests/conftest.py`, `tests/fakes.py` | 148, 73 | Fixtures and test doubles (Ch. 53) |
| `start.py` | 198 | One-step launcher: install, check, start the UI (Ch. 47) |
| `pyproject.toml`, `uv.lock`, `requirements*.txt` | | Packaging (Ch. 44) |
| `.env.example`, `.gitignore`, `.python-version`, `.streamlit/config.toml` | | Configuration |
| `docs/…` | | Documentation (this book, requirements, testing strategy, verification report) |
| `docs/project_book/build_book.py` | | Book generator |

## 86. Test index

| File | Tests |
|---|---|
| `tests/unit/test_records_policy.py` | normalize_item_name, case-insensitive lookup, exact decimals, duplicate items/customers, negative price, window boundaries, mixed assessment, unknown customer |
| `tests/unit/test_tools.py` | tool-name contract, history and date, enforced calculation, unknown customer, guardrails (4 variants), cumulative quote limit, prompt-only mode |
| `tests/unit/test_dataset.py` | bundled dataset valid, policy oracle, minimal dataset, 9 invalid-file variants, duplicate ids, duplicate items, size limit, unknown-tool warnings, file loading and resolution, unknown case |
| `tests/unit/test_offline_model.py` | customer ID extraction (4), requested-item extraction (8), reference variant, naive variant, asks for customer ID/items, retryable model-error classification |
| `tests/unit/test_deterministic_metrics.py` | refund outcome (3), tool coverage, forbidden tools, normalisation (7), args matching, argument match, LCS/order, answer consistency (8), runner status mapping |
| `tests/unit/test_judge_metrics.py` | pass/fail/cost, invalid scores (4), transient retry, bounded retry, permanent error + redaction, timeout, not applicable, is_transient, test-case construction, all 7 DeepEval metrics with fake judge, guard never calls LLM, failed execution |
| `tests/unit/test_results_storage_export.py` | case status (6), metric summary, run summary, store round trip/atomic/corrupt/delete, traversal (5), exports, comparison |
| `tests/unit/test_config_providers.py` | defaults, `.env` reading, invalid configuration (3), redaction, log redaction, provider status, builders/errors, real clients without network, judge adapter, model defaults per provider, `.env.example` valid |
| `tests/integration/test_engine.py` | offline run persisted, naive caught, guardrails effect, judge metrics, agent failure, timeout, recursion limit, preflight, interrupt + resume, changed dataset, engine failure |
| `tests/integration/test_cli.py` | doctor/metrics/dataset, validate errors, full workflow incl. exports/compare/delete, readable errors, module entry point |
| `tests/ui/test_app.py` | home (2), evaluate run, provider gating, results details, compare (2), playground, datasets, settings secrets |
| `tests/live/test_live_providers.py` | live agent + judge for Groq and OpenAI (opt-in) |

## 87. Requirements traceability matrix

| Req. | Implementation | Evidence |
|---|---|---|
| FR-1 | `refund/agent.py`, `tools.py`, `schemas.py`, `prompts.py` | `test_tools.py`, `test_offline_model.py`, engine tests |
| FR-2 | `refund/policy.py`, prompt rules 1–6 | `test_records_policy.py`, oracle test |
| FR-3 | `PolicyMode`, `tools.py` | `test_enforced_*`, `test_prompt_only_mode_has_no_guardrails`, `test_guardrails_keep_naive_refunds_correct` |
| FR-4 | `RefundLedger` | `test_tools.py`, `test_offline_reference_run_passes_and_is_persisted` |
| FR-5 | `evaluation/dataset.py` | `test_dataset.py`, `test_dataset_validate_reports_errors` |
| FR-6 | `get_current_date` uses `reference_date` | `test_history_and_date`, oracle test |
| FR-7 | `execution.py`, `tracing.py` | engine tests, `test_build_test_case_carries_trace_and_tools` |
| FR-8 | `metrics/deterministic.py` | `test_deterministic_metrics.py` |
| FR-9 | `metrics/judge.py` | `test_real_deepeval_metrics_run_with_fake_judge`; live Groq judge run (verification report §5) |
| FR-10 | thresholds in `RunRequest`/`RunConfig`; statuses | `test_runner_maps_outcomes_to_statuses`, judge runner tests |
| FR-11 | `aggregate.py` | `test_metric_summary_…`, `test_run_summary` |
| FR-12 | `storage.py` | `test_store_roundtrip_…`, CLI workflow test |
| FR-13 | `export.py` | `test_exports`, CLI export loop |
| FR-14 | `compare.py`, compare page | `test_compare_runs_…`, `test_compare_page` |
| FR-15 | `EvaluationEngine.resume` | `test_interrupted_run_can_be_resumed`, `test_resume_refuses_changed_dataset` |
| FR-16 | `providers/` | `test_config_providers.py`; live Groq runs (verification report §4–5); OpenAI not verified |
| FR-17 | `EvaluationEngine.preflight` | `test_preflight_reports_problems_before_running`, UI gating test |
| FR-18 | `cli.py` | `test_cli.py` |
| FR-19 | `ui/` | `test_app.py`, manual browser verification |
| FR-20 | `cli chat`, playground | `test_playground_chat_with_offline_agent`; CLI chat manual |
| FR-21 | `refund_support_v1.json` | `test_bundled_dataset_is_valid`, oracle test |
| NFR-1 | offline provider | clean-install verification, all offline tests |
| NFR-2 | `RunConfig`, `environment_info`, SHA-256, fingerprint | run record inspection, compare warnings test |
| NFR-3 | timeouts, recursion limit, retries, isolation, atomic saves, interrupt handling | engine and judge runner tests |
| NFR-4 | skip/error statuses, offline labels, score validation | `test_invalid_scores_become_errors`, UI offline notice |
| NFR-5 | `config.py`, `logging_utils.py`, storage id check, export CSV guard, UI path restriction | redaction, traversal, settings-secrets, export tests; bandit |
| NFR-6 | typed modules | ruff, mypy clean |
| NFR-7 | test doubles, isolation fixture | 158 offline tests |
| NFR-8 | semaphores, no infrastructure | engine design; concurrency used in tests |
| AC-1 … AC-9 | see `PRODUCT_REQUIREMENTS.md` §8 | `VERIFICATION_REPORT.md` |
| AC-10 | live run | Met on Groq (verification report §4–5); OpenAI not verified |

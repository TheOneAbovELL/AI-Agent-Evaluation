# Part IV — Source-code walkthrough

## 19. Final directory tree

```text
tracegrade/
├── .env.example               configuration template (tested to be valid)
├── .gitignore
├── .python-version            3.12
├── .streamlit/config.toml     UI theme and server options
├── README.md
├── start.py                   one-step launcher (python start.py)
├── pyproject.toml             package metadata, dependencies, tool configuration
├── uv.lock                    exact resolved dependency set
├── requirements.txt           pip export of uv.lock (runtime)
├── requirements-dev.txt       pip export of the dev group
├── src/tracegrade/
│   ├── __init__.py            version
│   ├── __main__.py            `python -m tracegrade`
│   ├── cli.py                 command-line interface
│   ├── config.py              Settings, PolicyMode, provider/model defaults
│   ├── errors.py              exception hierarchy
│   ├── logging_utils.py       formatters, redaction, configure_logging
│   ├── refund/                system under test
│   │   ├── records.py         purchase records + name normalisation
│   │   ├── policy.py          deterministic refund policy
│   │   ├── schemas.py         AgentReply, PurchaseItem
│   │   ├── prompts.py         system prompt + fingerprint
│   │   ├── tools.py           four tools, ledger, guardrails
│   │   └── agent.py           create_agent assembly
│   ├── providers/
│   │   ├── registry.py        ModelSpec, PROVIDERS, builders, status, connection check
│   │   ├── offline.py         OfflinePolicyChatModel (reference / naive)
│   │   └── judge_adapter.py   LangChain chat model -> DeepEval judge
│   ├── evaluation/
│   │   ├── dataset.py         schema, parsing, validation, bundled datasets
│   │   ├── models.py          result schema (RunRecord, CaseResult, ...)
│   │   ├── tracing.py         TraceRecorder callback
│   │   ├── execution.py       execute_case, extract_tool_calls
│   │   ├── metrics/
│   │   │   ├── base.py        MetricDefinition, MetricScore, NotApplicable
│   │   │   ├── deterministic.py  6 deterministic/heuristic metrics
│   │   │   ├── judge.py       7 DeepEval metrics, runner with retries
│   │   │   └── __init__.py    catalogue, suites, deterministic runner
│   │   ├── engine.py          EvaluationEngine, RunRequest, Preflight, events
│   │   ├── aggregate.py       case status, metric and run summaries
│   │   ├── storage.py         RunStore (JSON files)
│   │   ├── export.py          JSON / CSV / Markdown
│   │   └── compare.py         run comparison
│   ├── resources/datasets/refund_support_v1.json
│   └── ui/
│       ├── app.py             Streamlit entry point and navigation
│       ├── state.py           settings, store, dataset discovery, uploads
│       ├── components.py      tables, charts, case details, downloads
│       └── pages/             home, evaluate, results, compare, playground,
│                              datasets, settings_help
├── tests/                     unit/, integration/, ui/, live/, conftest.py, fakes.py
└── docs/                      requirements, discovery, testing, verification,
                               project_book/
```

Generated at runtime and git-ignored: `.venv/`, `runs/`, `datasets/` (uploads), `logs/`,
`.deepeval/` (empty folder DeepEval creates on import).

## 20. Configuration, errors and logging

### 20.1 `config.py`

*Purpose.* One typed source of configuration. *Inputs:* environment variables and an optional
`.env` in the working directory. *Output:* a `Settings` object.

* `Settings(BaseSettings)` with prefix `TRACEGRADE_` for application settings and the
  conventional unprefixed names `OPENAI_API_KEY`, `GROQ_API_KEY` for credentials (held as
  `SecretStr`).
* Validators: providers must be in `AGENT_PROVIDERS` / `JUDGE_PROVIDERS`; blank key or
  temperature strings become `None`; blank model names become the provider default
  (`DEFAULT_AGENT_MODELS`, `DEFAULT_JUDGE_MODELS`).
* `load_settings(**overrides)` converts Pydantic errors into a `ConfigurationError` naming the
  environment variable (e.g. `TRACEGRADE_AGENT_PROVIDER: must be one of offline, openai, groq`).
* `get_settings()` caches process-wide; the UI's *Reload configuration* clears the cache.
* Import side effect (deliberate, documented): `DEEPEVAL_TELEMETRY_OPT_OUT` is set to `1`
  with `os.environ.setdefault`.

*Failure modes:* invalid values → `ConfigurationError` (CLI exit 2, UI error banner).
*Tests:* `test_config_providers.py`.

### 20.2 `errors.py`

`TraceGradeError` (with optional `hint`) → `ConfigurationError` → `ProviderUnavailableError`;
`DatasetError`, `RunNotFoundError`, `StorageError`. Front ends catch `TraceGradeError` and show
the message and hint; any other exception is a genuine bug and is shown with a traceback.

### 20.3 `logging_utils.py`

`configure_logging(level, fmt, log_file, secrets)` configures the `tracegrade` logger with a
text or JSON formatter and a `RedactingFilter`. `redact()` masks `sk-…`, `gsk_…`, bearer tokens
and the literal values of configured keys. Structured context is passed as
`extra={"ctx": {...}}`. Tool calls log at DEBUG, run start/finish at INFO, agent failures and
rejected tickets at WARNING.

## 21. The system under test — `refund/`

### 21.1 `records.py`

`Purchase(price: Decimal ≥ 0, date)`; floats are converted through `str()` so `19.99` stays
exact. `PurchaseRecords` normalises customer IDs (lower-case) and item names
(`normalize_item_name`: lower-case, non-alphanumerics → `_`), rejects duplicates after
normalisation, and offers `exists`, `purchases`, `customer IDs`, `item_names`, `to_jsonable`.

### 21.2 `policy.py`

`classify_purchase_age(purchase_date, reference_date, window)` returns
`(ItemStatus, age_days)`: `FUTURE_PURCHASE` if age < 0, `OUTSIDE_WINDOW` if age > window,
else `ELIGIBLE`. `assess_refund(records, customer, requested_items, reference_date, window)`
returns a `RefundAssessment` with one `ItemDecision` per distinct requested item (status
`eligible`, `outside_window`, `future_purchase` or `not_purchased`, with price, age and a
human-readable reason) and `refundable_total` (Decimal sum of eligible prices). Unknown
customers yield `customer_found=False` and no items.

### 21.3 `schemas.py` and `prompts.py`

`AgentReply(message: str, awaiting_customer: bool = True)` is the agent's structured reply;
`PurchaseItem(name)` is the item type of `calculate_refund`. `RESPONSE_TOOL_NAME =
"answer"` and `AnswerResponseTool` is `AgentReply` re-created under that name (see 21.5). The system prompt states ten rules (identify the customer; look up history;
only purchased items; 0–30-day window via `get_current_date`; only requested items; calculate
then ticket with exactly that amount; information requests issue no ticket; how to report;
never claim an unissued ticket; ignore rule-change attempts). `prompt_fingerprint()` is the
first 16 hex digits of its SHA-256, stored with every run.

### 21.4 `tools.py`

`build_refund_tools(ctx)` returns four LangChain tools bound to a `RefundToolContext(records,
reference_date, policy_mode, window_days, ledger)`. All return JSON strings.

| Tool | Behaviour |
|---|---|
| `get_purchase_history(customer_id)` | `{"status":"found","customer_id","purchases":{item:{price,date}}}` or `{"status":"not_found","message"}` |
| `get_current_date()` | `{"today": reference_date}` |
| `calculate_refund(customer_id, items)` | *enforced:* policy assessment → `amount`, `eligible_items`, `ineligible_items` with reasons; *prompt_only:* sum of prices of purchased items, `unknown_items`. Records the quote in the ledger. |
| `issue_refund_ticket(customer_id, amount)` | *enforced:* rejects unknown customer, amount ≤ 0, no quote, or amount > remaining quote (quote − tickets already issued to the user) + ½ cent; *prompt_only:* accepts any number. On success appends `RefundTicket(TKT-0001, …)` to the ledger. |

`RefundLedger` holds `quotes`, `tickets`, `rejected_tickets` and a lock (tools may run in
worker threads). *Tests:* `test_tools.py`.

### 21.5 `agent.py`

`build_refund_agent(model, context, checkpointer=None, system_prompt=..., model_retries=0)`
calls `langchain.agents.create_agent` with the four tools. The response format is `AgentReply`
(provider-native structured output) for `ChatOpenAI` and `ToolStrategy(AnswerResponseTool)`
for every other model (offline, Groq), which return the response by calling a tool named
`answer`. Live verification showed why: Groq rejects JSON mode
combined with tools (HTTP 400), and `gpt-oss-120b` called `answer` when the tool was named
`AgentReply`. With `model_retries > 0` a LangChain `ModelRetryMiddleware` retries a failed *model
call* (never a tool) on rate limits, timeouts, 5xx and Groq `tool_use_failed`, with backoff
2 s × 2ⁿ capped at 30 s (`is_retryable_model_error`). The engine passes the agent spec's
`max_retries` (0 for the offline model). Native structured output is used only for
`ChatOpenAI`, which supports it together with tool calling. This replaced an earlier
rule that used the tool strategy only for the offline model.

A checkpointer (`InMemorySaver`) is passed only for multi-turn chat.

## 22. Providers — `providers/`

### 22.1 `registry.py`

`ModelSpec(provider, model, temperature, timeout_seconds, max_retries)` — serialisable,
credential-free, stored in run records. `PROVIDERS` describes `offline`, `openai`, `groq`
(package, key variable, default models, judge support). Functions:

* `provider_status(settings)` — package installed? credential present? (no network).
* `build_chat_model(spec, settings)` — `OfflinePolicyChatModel`, `ChatOpenAI` or `ChatGroq`
  with timeout, retries, temperature (omitted when `None`) and the key.
* `build_judge(spec, settings)` — DeepEval `OpenAIModel` for OpenAI, `LangChainJudgeModel` for
  Groq; offline cannot judge.
* `check_connection(spec, settings)` — one tiny request; only on explicit user action.
* `default_agent_spec`, `default_judge_spec` — from settings.

Missing package or key → `ProviderUnavailableError` with a hint.

### 22.2 `offline.py`

`OfflinePolicyChatModel(variant="reference"|"naive")` is a `BaseChatModel` whose `_generate`
inspects the conversation and returns the next action:

1. No customer ID in any human message → final reply asking for it (`awaiting_customer=True`).
2. No purchase-history result yet → call `get_purchase_history`.
3. Customer not found → final answer asking for a valid customer ID.
4. Information request (`no refund`, `what I purchased`, …) or no refund keyword → list
   purchases, no ticket.
5. Extract requested items: text after each `refund/return` keyword up to a clause break,
   split on `and`, `,`, `&`, `plus`, filler words and numbers removed, normalised; fall back to
   purchased item names mentioned anywhere.
6. Nothing requested → ask which items; nothing purchased among them → refuse.
7. *reference:* call `get_current_date`, classify each item with the policy; *naive:* treat all
   purchased requested items as eligible (no date check).
8. Call `calculate_refund` for eligible items; quote request → answer without ticket;
   amount 0 → refuse; else `issue_refund_ticket` with the calculated amount; report the
   ticket id, amount and non-refunded items.

Each step's `AIMessage.content` is a short plan/step sentence, so traces resemble an agent
that states its plan. Tool-call ids are deterministic (`offline_call_<n>`).

### 22.3 `judge_adapter.py`

`LangChainJudgeModel(chat_model, model_name)` implements DeepEval's `DeepEvalBaseLLM`.
`generate(prompt, schema)` tries `chat_model.with_structured_output(schema)`; on any failure
it logs a warning and returns the raw completion text, which DeepEval parses as JSON (raising
a clear error if invalid). `a_generate` is the async twin.

## 23. Evaluation core — `evaluation/`

### 23.1 `dataset.py`

Pydantic models `ExpectedToolCall`, `EvalCase`, `EvalDataset` (`extra="forbid"`, so typos in
field names are errors). Checks: case id pattern `^[a-z0-9][a-z0-9_-]{0,79}$`, unique ids,
non-negative `expected_refund_total`, no tool both expected and forbidden, at least one case,
valid customers (via `PurchaseRecords`). `parse_dataset(raw, source, max_bytes)` handles size
limit, UTF-8 (with BOM), JSON errors with line/column, and returns
`LoadedDataset(dataset, source, sha256)`. `warnings()` reports unknown tool names and missing
reference answers. `resolve_dataset(spec)` accepts `bundled:<name>`, a bare bundled name, or a
JSON path.

### 23.2 `models.py`

The persisted result schema (Chapter 80 has the full field list): `ToolCallRecord`,
`TicketRecord`, `AgentExecution`, `MetricOutcome`, `CaseResult`, `RunConfig`,
`MetricSummary`, `RunSummary`, `RunRecord`, with status enums `ExecutionStatus`,
`MetricKind`, `MetricStatus`, `CaseStatus`, `RunStatus`. All timestamps are UTC.

### 23.3 `tracing.py`

`TraceRecorder(BaseCallbackHandler)` records chat-model calls (`on_chat_model_start`,
`on_llm_end`, `on_llm_error`) and tool calls (`on_tool_start/end/error`) with offsets and
durations, sums token usage from `usage_metadata`, clips long text to 4,000 characters, and
`build()` returns the agent span with all LLM and tool spans as ordered children (LangGraph's
internal chain nodes are flattened away). Each LLM span lists only messages new since the
previous call. `raise_error = False`: a recorder problem never breaks the agent run.
`tool_spans()` provides evidence when the run fails.

### 23.4 `execution.py`

`execute_case(case, dataset, model, policy_mode, timeout_seconds, recursion_limit, secrets)`:

1. Fresh `RefundToolContext` and agent for the case.
2. `agent.ainvoke` under `asyncio.wait_for(timeout)` with the recorder, a recursion limit and
   a unique thread id.
3. Exceptions become statuses, not crashes: `TimeoutError` → `timeout`;
   `GraphRecursionError` → `error` ("possible tool-calling loop"); anything else → `error`
   with a redacted, truncated message.
4. Reply text from the structured `AgentReply`; otherwise the last AI text plus a warning.
5. Tool calls from AI messages paired with tool outputs by `tool_call_id`, excluding the
   `answer` response tool; if the run raised, reconstructed from the trace.
6. Tickets and rejected tickets from the ledger, latency, tokens.

### 23.5 Metrics — `metrics/`

* `base.py`: `MetricDefinition(id, name, kind, description, default_threshold, evidence,
  method, requires_judge, tags)`, `MetricScore(score, reason)`, `NotApplicable`.
* `deterministic.py`: six functions `(case, execution) -> MetricScore` plus helpers
  `normalize_value`, `args_match`, `longest_common_subsequence` (Chapter 30 gives formulas).
* `judge.py`: definitions of the seven DeepEval metrics, `build_test_case`,
  `check_applicable`, `make_deepeval_metric`, `is_transient`, `run_judge_metric`, the task
  description and GEval steps, and `NoLLMGuard`.
* `__init__.py`: `METRICS` catalogue (13 metrics in display order), suites `deterministic`
  (7 that need no judge), `judge` (6), `all`; `resolve_metric_ids`;
  `run_deterministic_metric` (maps scores to `passed`/`failed`, `NotApplicable` to
  `skipped`, unexpected exceptions to `error`).

### 23.6 `engine.py`

`RunRequest` (dataset, case ids, agent spec, judge spec, metric ids, thresholds, policy mode,
concurrency 1–16, recursion limit, label). `EvaluationEngine(settings, store,
chat_model_factory, judge_factory, judge_backoff_seconds)`; the factories are injectable for
tests.

* `preflight(request)` → `Preflight(errors, warnings, info)` without executing anything:
  unknown cases/metrics, thresholds outside [0, 1], agent and judge buildable, judge metrics
  that will be skipped, dataset warnings, an offline notice or an API-usage estimate.
* `run(request, on_event, should_cancel)` → `RunRecord`. Builds the judge once; evaluates
  pending cases under a case semaphore (`max_concurrency`) and judge calls under a judge
  semaphore (`3 × max_concurrency`); saves after every case; emits `run_started`,
  `case_started`, `case_finished`, `run_finished` events.
* `resume(run_id, retry_errors)` reloads a run, re-resolves its dataset, refuses if the
  SHA-256 changed, and evaluates missing cases (optionally re-running agent-error cases).
* Metric handling per case: if the agent did not complete, every metric is `skipped` with the
  reason; deterministic metrics run synchronously; judge metrics without a judge are
  `skipped`; the rest run concurrently via `run_judge_metric`.
* Exception policy: `Exception` → run `failed` (saved, re-raised); other `BaseException`
  (Ctrl+C, cancellation, Streamlit stop) → `interrupted` (saved, re-raised).
* `environment_info()` records Python, platform and versions of eight packages.

### 23.7 `aggregate.py`, `storage.py`, `export.py`, `compare.py`

* `case_status`, `summarize_metric`, `summarize_run` (formulas in Chapter 31).
* `RunStore(root)`: `save` (temp file + `fsync` + `os.replace`, retried briefly on Windows
  `PermissionError`), `load`, `exists`, `list_runs` (newest first; unreadable files logged and
  skipped), `delete`. `validate_run_id` allows only `[A-Za-z0-9][A-Za-z0-9_-]{0,99}`.
* `export(record, fmt)` → `(content, filename, mime)` for `json`, `csv`/`metrics-csv`,
  `cases-csv`, `md`. CSV cells starting with `= + - @` are prefixed with `'`.
* `compare_runs(baseline, candidate)` → metric deltas (candidate − baseline), per-case status
  changes, regressions/improvements and compatibility warnings (dataset hash, reference date,
  thresholds, judge, policy mode, prompt, incomplete runs, metrics in only one run).

## 24. The CLI — `cli.py`

`build_parser()` defines eight commands; `main(argv)` loads settings (optionally from
`--env-file`), configures logging (WARNING with `--quiet`), dispatches, and maps
`TraceGradeError` → message + hint + exit 2, `KeyboardInterrupt` → exit 130. `evaluate`
prints preflight info/warnings/errors, streams one line per finished case, prints a metric
table and the run file path, and returns 1 for incomplete runs or (with `--fail-on-failure`)
failures. `chat` runs a multi-turn loop with an `InMemorySaver` and prints tool calls per
turn. `ui` launches `python -m streamlit run <package>/ui/app.py` with a fixed argument list.

## 25. The UI code — `ui/`

`app.py` sets the page configuration, configures logging once (`st.cache_resource`) and
declares the navigation (Overview; Evaluate: New evaluation, Run results, Compare runs;
Explore: Agent playground, Datasets; Help: Settings & help). `state.py` centralises settings
(errors shown, page stopped), the run store, dataset discovery (bundled + datasets folder
only), a cached dataset loader keyed by file modification time, and upload saving with a
sanitised file name. `components.py` holds rendering helpers; notably `md()` escapes `$` and
`\` in data text (Streamlit markdown would otherwise render `$…$` as LaTeX). Chapter 36
describes the pages.

## 26. Error propagation summary

| Origin | Becomes | Shown as |
|---|---|---|
| Bad configuration | `ConfigurationError` | CLI exit 2 + hint; UI error banner |
| Bad dataset | `DatasetError` | CLI exit 2; UI error under the selector |
| Preflight problems | list of errors | CLI exit 2; UI errors, run button disabled |
| Agent exception / timeout / loop | `AgentExecution.status` + message | case status `error`, metrics skipped |
| Metric not applicable | `NotApplicable` | metric `skipped` with reason |
| Judge failure / invalid output | `MetricOutcome.status = error` | case `incomplete` |
| Engine bug | exception | run `failed` saved; traceback |
| Interrupt | `BaseException` | run `interrupted` saved; resumable |
| Storage failure | `StorageError` | message with path |

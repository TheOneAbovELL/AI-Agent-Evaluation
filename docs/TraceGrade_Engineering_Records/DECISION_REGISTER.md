# Decision register

Each entry: context → decision → alternatives considered → consequences.

### D-01 Build a new, independently structured project
* **Context:** The reference repository was a set of scripts with import-time side effects,
  stale documentation and no tests. The user asked for an independent implementation that
  uses the reference only as a blueprint.
* **Decision:** New project directory `tracegrade/` with its own package, manifests, docs and
  tests. The reference stays unmodified in a sibling folder and is never imported.
* **Alternatives:** Refactor in place (rejected: would carry obsolete structure and names);
  fork and prune (rejected: same).
* **Consequences:** Clean provenance in engineering docs; no runtime dependency on the reference.

### D-02 Name: TraceGrade
* **Context:** The original name ("LangChain Agent Evaluation System") was generic and tied to
  a repository layout that no longer exists.
* **Decision:** "TraceGrade" — grading agents from their execution traces and side effects.
  Package `tracegrade`, CLI `tracegrade`.
* **Alternatives:** Keep the descriptive name (acceptable but long and collides with the old
  scaffold package name).

### D-03 Packaging: `src/` layout, hatchling, uv lockfile
* **Decision:** `src/tracegrade`, build backend `hatchling`, dependency management with uv
  (`uv.lock`), plus an exported `requirements.txt` for pip users.
* **Alternatives:** `uv_build` (the reference pinned `<0.13` while the installed uv is 0.13.1;
  hatchling avoids coupling the build backend to the uv version); Poetry (unnecessary).

### D-04 The refund policy as deterministic code, cross-checked against the dataset
* **Context:** In the reference the policy existed only as prose in the prompt; expected
  outcomes were hand-written and the README admits they could disagree with the data.
* **Decision:** `refund/policy.py` implements the rules; tests assert that every case's
  `expected_refund_total` (and the expected `calculate_right_refund` items) equals the
  policy's result ("oracle" test).
* **Consequences:** Dataset errors are caught by CI; the same code powers tool guardrails and
  the offline model.

### D-05 Fixed reference date per dataset
* **Decision:** `get_today_date` returns the dataset's `reference_date`; the playground and
  CLI chat can opt into the real date.
* **Alternatives:** Machine date (non-reproducible, the reference's main correctness problem);
  freezing time globally (invasive).

### D-06 Two policy modes; guardrails with a cumulative limit
* **Decision:** `enforced` (default): `calculate_right_refund` applies the policy and records a
  quote; `issue_refund_ticket` rejects unknown users, non-positive amounts, missing quotes, and
  any amount above the *remaining* quote (tickets already issued consume it). `prompt_only`
  reproduces a plain lookup with no validation.
* **Why both:** Guardrails are what a production system should have; `prompt_only` is what
  lets an evaluation measure whether the *model* follows the policy.
* **Found during testing:** the first guardrail compared each ticket with the full quote, so
  several tickets could exceed it in total. Fixed and covered by a test.

### D-07 Tool ledger as ground truth; `refund_outcome` metric
* **Decision:** Tools record tickets (and rejections) in a per-session ledger; the primary
  outcome metric compares the ledger with `expected_refund_total` instead of trusting the
  agent's wording or an LLM judge.
* **Consequences:** A cheap, exact, judge-independent gate; the heuristic
  `answer_action_consistency` metric then checks that the wording matches the ledger.

### D-08 Record traces with an own LangChain callback, not DeepEval's tracing
* **Context:** DeepEval's `CallbackHandler` + `evals_iterator` own the evaluation loop and keep
  traces in global state that is cleared (and optionally uploaded to Confident AI) after each
  trace; a prototype showed `trace_manager.traces` empty after the run.
* **Decision:** `TraceRecorder` builds a compact span tree in DeepEval's dictionary shape
  (`name/type/input/output/children`) and attaches it as `LLMTestCase._trace_dict`.
* **Trade-off:** Uses one private DeepEval attribute (`_trace_dict`), which is covered by
  tests that run all DeepEval metric classes; a DeepEval upgrade that renames it will fail
  those tests loudly.

### D-09 Call DeepEval metrics directly
* **Decision:** For each case and metric: build a fresh metric instance, `await
  metric.a_measure(test_case)` under `asyncio.wait_for`, retry only transient errors
  (timeouts, connection errors, 429, 5xx) with exponential backoff and jitter, at most
  `judge_max_retries` times; validate the score is a finite number in [0, 1].
* **Alternatives:** `deepeval.evaluate()` (no per-metric timeout/retry control, results in
  DeepEval's own structures, terminal output).

### D-10 `NoLLMGuard` for DeepEval's tool-correctness metric
* **Context:** DeepEval's constructors require a judge model and default to OpenAI, which
  fails without a key even for `ToolCorrectnessMetric`, whose scoring is deterministic unless
  `available_tools` is set.
* **Decision:** Pass a guard model that raises if called. The metric runs offline; if a
  DeepEval change ever makes it call the LLM, it errors instead of silently spending money.

### D-11 Offline reference model
* **Decision:** A rule-based `BaseChatModel` drives the real graph and tools; variants
  `reference` (follows the policy) and `naive` (skips date checks). Labelled in CLI output,
  UI banners, Markdown exports and the run record (`provider = offline`).
* **Alternatives:** No offline mode (the product would be unusable without a key); canned
  responses (would not exercise the agent, tools or ledger).
* **Limitation:** English-only, regular-expression parsing; it is a pipeline check, not a model.

### D-12 Providers: OpenAI and Groq; LangChain adapter for non-native judges
* **Context:** The reference used OpenAI; the user has no paid key and will provide a Groq key.
* **Decision:** Registry with `offline`, `openai` (ChatOpenAI; DeepEval's native
  `OpenAIModel` judge) and `groq` (ChatGroq; `LangChainJudgeModel` adapter). Models default per
  provider and are configurable.
* **Adapter behaviour:** structured output first, raw text fallback parsed by DeepEval;
  malformed output becomes a metric error.

### D-13 One JSON file per run, written atomically and incrementally
* **Alternatives:** SQLite (queries not needed; adds migration concerns), a server database
  (unjustified). JSON files are inspectable, diffable and easy to back up.
* **Consequences:** Listing reads every file (fine for hundreds of runs; noted as a scaling limit).

### D-14 Reuse from the reference
* **Reused:** the synthetic purchase records (values; dates normalised to ISO and one
  boundary customer added), the refund policy wording (rewritten), the four tool names and
  their argument names (they are the evaluation contract), seven scenario sentences, the
  seven DeepEval metric choices, their thresholds, and the idea of running the agent once per
  case. **No source file or function was copied.**
* **Licensing:** the reference repository has no licence file. The reused material is small,
  synthetic sample data and short sentences; the user supplied the reference and should
  confirm they may reuse it. Recorded in known issues.

### D-15 Dropped from the reference
| Item | Reason |
|---|---|
| Seven per-metric scripts | Duplicated the runner with divergent settings; replaced by `--metrics` / `--suite` |
| `understanding_metrics/` multiplication demos | Separate toy agents with hard-coded models; their teaching intent is covered by the metric reference (UI, `tracegrade metrics`, book Part V) on the real scenario |
| `asyncio>=4.0.0` dependency | PyPI placeholder named like a standard-library module |
| `portalocker[win32]` | Already a DeepEval dependency |
| `deepeval[inspect]` extra | Terminal inspector not used |
| `src/langchain_agent_evaluation_system` scaffold and broken entry point | Replaced by `tracegrade.cli:main` |
| Screenshots of an old run | Not reproducible; the book contains screenshots of TraceGrade itself |

### D-16 Streamlit multipage UI
* **Decision:** Streamlit with `st.navigation`; the UI calls the same engine as the CLI; no
  JavaScript build.
* **Alternatives:** Gradio (weaker for multi-page dashboards), NiceGUI (less common), a
  JS front end (explicitly unwanted).

### D-17 No combined overall score
* **Decision:** Report each metric separately plus a case pass rate; never average different
  metrics. Mixing exact checks with judge opinions in one number would hide which is which.

### D-18 Do not retry a whole agent run
* **Decision:** Agent runs are not retried by TraceGrade because tool calls have side
  effects (tickets). Provider clients retry transient errors per model call.

### D-19 DeepEval telemetry off by default
* **Decision:** `DEEPEVAL_TELEMETRY_OPT_OUT=1` is set (with `setdefault`, so an explicit user
  value wins) when configuration loads.

### D-20 No Docker / Compose
* **Decision:** Not provided: a local Python app with file storage and no system packages
  gains little from a container, and the user asked not to add infrastructure for appearance.

### D-21 30-day window interpretation
* **Decision:** Eligible iff `0 <= age_days <= window` (inclusive). Encoded once in
  `classify_purchase_age`, tested at 0, 30, 31 and −1 days, and stated in the prompt.

### D-22 Defaults that work without configuration
* **Decision:** Agent provider defaults to `offline`, judge to `none`. Judge metrics are then
  *skipped* with a reason (never estimated).

### D-23 Exclude the structured-response tool from "tools called"
* **Decision:** LangChain's response tool (tool strategy; named `answer`, see D-28) is filtered out of tool
  calls so tool metrics only see real tools.

### D-24 Self-contained JSON datasets
* **Decision:** Customers, reference date and cases in one JSON file whose SHA-256 identifies
  the run inputs. JSON (not YAML) to avoid an extra dependency and ambiguity.

### D-25 Async engine with bounded concurrency
* **Decision:** `asyncio` with a case semaphore (`max_concurrency`) and a judge semaphore
  (3× cases); each case is isolated (own agent, tools, ledger). The UI calls `asyncio.run`
  in the script thread; engine events update the progress display.
* **Interrupts:** any `BaseException` (Ctrl+C, cancellation, Streamlit's `StopException`)
  marks the run `interrupted` and saves it; `resume` completes it.

### D-26 UI file access restricted
* **Decision:** The UI lists only bundled datasets and files in `TRACEGRADE_DATASETS_DIR`;
  uploads are validated, size-limited and saved under a sanitised name. No free-form paths.

### D-27 Model defaults follow the provider
* **Context:** A single default model string (e.g. an OpenAI model name) is wrong when the
  provider is switched to Groq.
* **Decision:** `TRACEGRADE_AGENT_MODEL` / `TRACEGRADE_JUDGE_MODEL` blank = the selected
  provider's default.

### D-28 Groq compatibility fixes found by live verification (2026-10-24)
* **Context:** The first live run with `groq:openai/gpt-oss-120b` failed in ways no test double
  reproduced: (1) LangChain's automatic structured-output strategy chose JSON mode, which Groq
  rejects together with tools (HTTP 400); (2) the model called `answer` while the response tool
  was named `Answer` (HTTP 400 `tool_use_failed`); (3) the on-demand tier's 8,000
  tokens-per-minute limit produced HTTP 429 on most cases; (4) the judge adapter's default
  structured-output method failed on every call.
* **Decision:** Tool strategy for every model except `ChatOpenAI`; response tool renamed
  `answer`; `ModelRetryMiddleware` around model calls (rate limits, timeouts, 5xx,
  `tool_use_failed`) with exponential backoff; defaults raised to 4 retries and a 300 s case
  timeout; Groq judge uses `method="json_schema"`.
* **Why retries are safe here:** they repeat a *model call* only; a failed model call has not
  executed any tool, so no ticket can be duplicated (D-18 still holds for whole runs).
* **Consequence:** Runs on low TPM tiers are slow (minutes per case with judges); use
  `--concurrency 1`.

### D-29 Product contains only original material (user requirement, 2026-10-24)
* **Decision:** New tool/argument names, reply schema, customer-ID scheme, prompt and dataset;
  engineering records moved out of the repository; reference copies deleted from the
  workspace. Supersedes D-14 (reuse of sample data and tool names): nothing from the
  reference remains in the repository.
* **Provenance:** these records (outside the repository) keep the history.

### D-30 Single launcher `start.py`
* **Decision:** A standard-library-only script so it runs before dependencies exist; prefers
  uv (exact lock), falls back to venv + pip (pinned requirements) with an install marker to
  skip unchanged installs; runs the provider check; starts Streamlit and opens the browser.
* **Alternatives:** `.bat` + `.sh` pair (two files, platform-specific); Makefile (not on
  Windows by default).

### D-31 Default Groq models: Qwen agent, gpt-oss judge
* **Context:** Live comparison on 4 cases: `qwen/qwen3.8-27b` completed 4/4 with structured
  replies; `gpt-oss-120b` failed 3/4 (`output_parse_failed`, rate limits).
* **Decision:** Agent default `qwen/qwen3.8-27b`; judge default `openai/gpt-oss-120b` (a different
  model family reduces self-preference bias).

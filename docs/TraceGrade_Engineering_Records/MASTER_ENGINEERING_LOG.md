# Master engineering log

Chronological record of how TraceGrade was built. Dates are 2026-10-23 (local time, UTC+5:30)
unless stated. Commands and outputs are summarised here; full command records are in
`BUILD_AND_RUN_LOG.md`, decisions in `DECISION_REGISTER.md`.

## 1. Initial condition

* Workspace folder `AI Agent Evaluation/` contained only `desktop.ini`.
* Input: a ZIP archive of the reference project (281,535 bytes) in the user's Downloads.
* Tooling found: Python 3.13.3 (system), uv 0.13.1, Node 22 (unused), no pandoc, no LaTeX.
* No `OPENAI_API_KEY`. An `ANTHROPIC_API_KEY` was present in the environment.

## 2. Inspection

* Extracted the ZIP unchanged to `_original_extract/` and read every source file in full
  (agent, tools, data, prompt, schemas, evaluation scripts, metric demos, README).
* Findings: README/code mismatches, broken entry point, import-time client construction, a
  moving "today", prompt-only policy with no guardrails, no persistence, no tests (details in
  `docs/PROJECT_DISCOVERY_AND_BASELINE.md` §5).

## 3. Baseline

* Copied the reference to `_baseline_env/` and ran `uv sync --locked` (Python 3.12.15,
  deepeval 4.2.8, langchain 1.4.4, langgraph 1.2.14).
* Ran: compileall (OK); agent import (fails: missing OpenAI credentials); direct tool calls
  (work; `issue_refund_ticket("nobody", -500)` accepted); console script (ImportError);
  `eval_all.py` (fails at import); README paths (missing files).
* No LLM-backed baseline possible without a key.

## 4. Decision point: providers

* Asked the user whether the present Anthropic key could be used for a small live run. Answer:
  *no paid API key; a Groq API key will be provided later.* Consequently: Groq provider added,
  no paid calls made, live verification deferred (see known issues).

## 5. Requirement change during the work

* The user added a second instruction: treat the ZIP as a **blueprint**, build a clean,
  independently structured project with its own identity, leave no legacy remnants, keep the
  reference unchanged, and run an independent-build audit. The plan was adjusted before any
  product code was written: new folder `tracegrade/`, new name, no shims for old scripts.

## 6. DeepEval investigation

* Read DeepEval 4.2.8 sources: `TaskCompletionMetric` reads `test_case._trace_dict`; the
  evaluation loop attaches traces from global tracing state.
* Prototype: a scripted chat model through `create_agent` with DeepEval's `CallbackHandler`
  produced a structured response, but `trace_manager.traces` was empty afterwards (traces
  are finalised/cleared). Decision D-08: record traces with an own callback.
* `ToolCorrectnessMetric()` without a judge raised "OpenAI API key is not configured";
  with a guard model it computed scores without any LLM call (D-10). Also observed: list
  parameters are compared order-sensitively.

## 7. Implementation (core)

Order of work, each step smoke-tested before the next:

1. `pyproject.toml` (hatchling, dependencies chosen for the new design), `uv lock` → 143
   packages; DeepEval resolved to 4.3.1, LangChain 1.4.7, langchain-groq 1.1.3,
   Streamlit 1.66.1.
2. Bundled dataset `refund_support_v1.json`: 11 customers (10 from the reference data with ISO
   dates + a synthetic boundary customer), 16 cases, reference date 2026-10-15.
3. `errors.py`, `config.py` (pydantic-settings, `SecretStr`, readable validation errors),
   `logging_utils.py` (text/JSON formatters, redaction).
4. `refund/`: records, policy, schemas, prompt (+ fingerprint), tools with ledger and
   guardrails, agent factory.
5. `providers/`: offline model (reference/naive), registry (offline/openai/groq), judge adapter.
   Smoke test: offline agent through the real graph produced the expected refund for all 16
   cases.
6. `evaluation/`: dataset loader, models, trace recorder, execution, deterministic metrics,
   DeepEval metric runner, registry, aggregation, storage, export, compare, engine.
   Smoke test: full offline run — reference variant 16/16 passed; naive variant caught by
   process metrics; judge metrics reported as skipped.
7. `cli.py` and `__main__.py`. Smoke test: `doctor`, `evaluate` (naive + prompt_only showed
   wrong refunds caught by `refund_outcome`).

## 8. Implementation (UI)

* Streamlit multipage app: overview, new evaluation, results, compare, playground, datasets,
  settings & help. Verified in the Claude desktop browser pane:
  - First real run from the UI: 16/16 completed and results page rendered.
  - **Bug:** timestamps shown in UTC without a label → converted to local time.
  - **Bug:** Altair hid alternate axis labels → `labelOverlap=False`, stacked layout.
  - **Bug:** `$` in answers rendered as LaTeX math ("$30 (book $23 + pen $7)") → `md()`
    escaping helper applied to all data text.
  - **Bug:** charts rendered squashed → pass explicit `height` to `st.altair_chart`
    (Streamlit 1.66 ignores the Vega height with `height="content"` in this layout).
  - **Bug:** offline provider listed "credential present" → "not needed".
  - Compare page showed "0.30" instead of "−0.30": investigated with the CLI and a zoomed
    capture — a screenshot-downscaling artefact, not a bug.
  - Streamlit only hot-reloads page scripts, so component changes required server restarts.

## 9. Testing and debugging

* Wrote unit, integration, UI (AppTest) and opt-in live tests.
* **Bug found by tests:** cumulative guardrail gap — several tickets could exceed the quote in
  total. Fixed (`remaining = quote − issued`), test added.
* **Bug found by tests:** when the agent run raised (e.g. recursion limit), tool calls were
  lost. Fixed: reconstruct from the trace recorder, with a warning.
* **Test-isolation issue:** the CLI configured the global logger with a handler bound to
  pytest's captured stderr; later tests logged to a closed stream. Fixed in `conftest.py`.
* DeepEval auto-registers a pytest plugin → disabled with `-p no:deepeval`.
* All seven DeepEval metric classes executed through TraceGrade's runner with a schema-filling
  test-double judge. Observation recorded: plan metrics return 1.0 when no plan is found.

## 10. Static analysis

* `ruff format` (34 files reformatted), `ruff check` (19 issues fixed; UI page prose exempt
  from line length), `mypy` (46 errors, mostly an untyped `**dict` pattern → typed; a loop
  variable reused with two types in `export.py`), `bandit` (4 low findings reviewed: fixed
  argv subprocess, retry jitter `random`, one `assert` replaced), `pip-audit` (no known
  vulnerabilities).

## 11. Configuration refinements

* Model defaults now follow the provider (D-27); `.env.example` is itself tested as a valid
  configuration.

## 12. Clean-environment verification

* First attempt in the session's temporary folder: `uv sync --locked` succeeded but imports
  of `openai` failed — the copy's path exceeded Windows' 260-character limit (265 chars).
  Documented as an environment constraint.
* Second attempt in `_clean_check/` (normal path length): found that the copy step's
  `--exclude=datasets` had also removed the bundled `resources/datasets` folder. Copy fixed
  with anchored excludes; `resources/` made an explicit package for robustness. Final results
  in `VERIFICATION_REPORT.md`.

## 13. Documentation

* README, `.env.example`, `.gitignore`, `requirements*.txt`, discovery, requirements, testing
  strategy, verification report, engineering log, project book with a regeneration script.

## 14. Deviations from the original plan

* No live LLM verification (no permitted key during the session).
* Docker deliberately not provided (D-20).
* The metric-tutorial scripts were not ported (D-15).

## 15. Live verification with Groq (2026-10-24)

The user supplied a Groq API key; it was stored only in the git-ignored `tracegrade/.env`.

* `doctor --ping`: `groq:openai/gpt-oss-120b replied: 'pong'`.
* First live run found four integration bugs no test double reproduced (decision D-28):
  JSON mode + tools rejected (400); response tool called by a lower-case name (400
  `tool_use_failed`); 8,000 tokens/minute tier → 429s; judge structured output failing with
  LangChain's default method. Fixes: tool strategy for non-OpenAI models, `ModelRetryMiddleware`
  on model calls, `json_schema` judge method, higher default retries/timeout.
* The live test then **passed** (3 cases, all 13 metrics, 11 min).
* After the redesign of section 16, further live findings: Groq rejects a plain-text final
  answer while a tool call is forced ("Tool choice is required…") → a `ChatGroq` subclass relaxes
  forced tool choice to `auto` and the prompt asks the model to finish with the `reply` tool;
  `gpt-oss-120b` leaked reasoning into output (`output_parse_failed`) → compared models on 4
  cases: `qwen/qwen3.8-27b` 4/4 clean, `gpt-oss-120b` 1/4 → Qwen became the default Groq agent;
  the judge default stays `gpt-oss-120b` (different family).
* The diagnostic runs exhausted `gpt-oss-120b`'s 200,000 tokens/day quota; daily-quota 429s
  are now treated as non-retryable (agent and judge).
* Final live agent run (all 16 cases, deterministic metrics): see the verification report.

## 16. Redesign requested by the user: no traces of the reference project

The user asked that the repository contain only what was built here, with no mention or
trace of the supplied ZIP, that the engineering logs live outside the repository, and that a
single start file run the whole application.

* Renamed the agent's contract: tools `get_purchase_history`, `get_current_date`,
  `calculate_refund`, `issue_refund_ticket` with arguments `customer_id`, `items`, `amount`;
  reply schema `AgentReply(message, awaiting_customer)` returned through a `reply` tool;
  customer IDs `C1001`-style instead of usernames.
* Rewrote the system prompt from scratch.
* Replaced the bundled dataset with newly invented customers, products, dates and scenario
  wording (reference date 2026-11-20); the oracle test confirms consistency.
* Rewrote all tests that used the old sample data; 158 offline tests pass.
* Added `start.py` (stdlib only): creates `.env`, installs with uv or pip, runs `doctor`,
  starts Streamlit on a free port and opens the browser. Verified: HTTP 200 after 4 s.
* Moved `docs/engineering_log/*` and the discovery report to `TraceGrade_Engineering_Records/`
  next to the project; removed reference-related content from the book (Part II replaced by a
  chapter on the refund domain; Part XI rewritten; appendices H–J removed).
* Deleted the workspace copies `_original_extract/` and `_baseline_env/`. The original ZIP in
  the user's Downloads folder was not touched.
* These records keep the history of the reference analysis because they are the honest
  provenance of the work; they are delivered separately from the product.

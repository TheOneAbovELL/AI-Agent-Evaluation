# Product requirements — TraceGrade 1.0

Every requirement maps to an implementation and a test, or to a documented limitation, in
the traceability matrix (project book, Chapter 87).

## 1. Problem statement

A tool-using agent can produce a plausible final answer while doing the wrong thing:
refunding an ineligible item, skipping a policy check, calling a tool with wrong
arguments, or claiming an action it never took. Evaluating such agents requires looking
at the **trajectory and side effects**, not only the reply, and doing so in a way that is
reproducible, inspectable and affordable.

## 2. Intended users and use cases

| User | Use case |
|---|---|
| Agent developer | Check a prompt/model/tool change against a fixed scenario set; inspect failures case by case; compare with the previous run |
| ML / evaluation engineer | Combine deterministic gates with LLM-judge signals; study judge behaviour; add scenarios and metrics |
| Learner | Understand what each agent metric measures on a concrete example, including without an API key |
| CI pipeline | Run the deterministic suite and fail the build on regressions |

## 3. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | Provide a tool-using customer-support refund agent (LangChain `create_agent`) with the tools `get_purchase_history`, `get_current_date`, `calculate_refund`, `issue_refund_ticket` and a structured reply (`message`, `awaiting_customer`). |
| FR-2 | Encode the refund policy (customer must exist; only purchased, requested items; purchase age 0–30 days; no future purchases) in the prompt **and** as deterministic code. |
| FR-3 | Support two policy modes: `enforced` (tools validate eligibility and ticket amounts) and `prompt_only` (policy only in the prompt). |
| FR-4 | Record every ticket the tools issue (and every rejected ticket) in a per-session ledger. |
| FR-5 | Load evaluation datasets from self-contained, schema-validated JSON (records, reference date, cases with expected output, expected tools with optional parameters, forbidden tools, expected refund total). Reject invalid files with precise messages. |
| FR-6 | Use the dataset's reference date as the agent's "today" for reproducibility. |
| FR-7 | Run the agent once per case, capturing answer, structured-response presence, tool calls with arguments and outputs, tickets, an execution trace, latency and token usage where reported. |
| FR-8 | Compute deterministic metrics: refund outcome, expected tool coverage, forbidden tool avoidance, tool argument match, tool order, answer/action consistency (heuristic). |
| FR-9 | Compute DeepEval metrics: task completion, step efficiency, plan quality, plan adherence (trace-based), argument correctness, tool correctness, answer correctness (GEval). |
| FR-10 | Per-metric configurable thresholds; pass iff `score >= threshold`; distinguish passed, failed, error and skipped. |
| FR-11 | Aggregate per metric (evaluated, passed, failed, errors, skipped, mean, min, max, pass rate) and per run (case statuses, case pass rate, tickets, tokens, judge cost, latency). |
| FR-12 | Persist each run (configuration, environment, per-case results, summary) locally; list, load and delete runs. |
| FR-13 | Export runs as JSON, metric CSV, case CSV and Markdown. |
| FR-14 | Compare two runs: metric deltas, per-case status changes, compatibility warnings. |
| FR-15 | Resume an interrupted run without re-running completed cases; refuse if the dataset content changed. |
| FR-16 | Providers: offline (credential-free deterministic stand-in, clearly labelled), Groq and OpenAI for the agent; Groq and OpenAI for the judge; judge optional. |
| FR-17 | Validate a run before executing it (unknown cases/metrics, bad thresholds, missing credentials/packages) and report what will be skipped and what will cost money. |
| FR-18 | CLI covering evaluate, resume, runs (list/show/export/compare/delete), dataset (list/validate/show), metrics, doctor, chat, ui. |
| FR-19 | Streamlit UI: overview, new evaluation with live progress, results (summary, charts, case details, trace, exports, history), compare, agent playground (multi-turn chat with tool display), datasets, settings & help. |
| FR-20 | Interactive multi-turn conversation with the agent (CLI `chat` and UI playground). |
| FR-21 | A bundled synthetic dataset covering eligible, ineligible, partial, mixed, unknown-customer, quote, missing-customer-ID, unpurchased-item, future-date, 30-day boundary and prompt-injection scenarios. |

## 4. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | Usable end to end without any API key (offline mode) on Windows, macOS and Linux with Python 3.12–3.13. |
| NFR-2 | Reproducibility: every run records dataset SHA-256, reference date, models, thresholds, policy mode, prompt fingerprint and package versions. |
| NFR-3 | Reliability: agent timeouts, recursion (step) limit, bounded judge retries with backoff for transient errors only, partial failures isolated per case and per metric, atomic incremental persistence, interruption handling. |
| NFR-4 | Honesty: no fabricated scores; unavailable metrics reported as skipped with a reason; offline runs labelled; judge output that is malformed or out of range becomes an error. |
| NFR-5 | Security: secrets only from environment/.env, held as `SecretStr`, redacted in logs and error messages, never stored in runs or exports; UI cannot read arbitrary paths; uploads size-limited and validated; CSV formula injection neutralised; run ids validated against path traversal; DeepEval telemetry off by default. |
| NFR-6 | Maintainability: typed (mypy clean), linted (ruff), modular, no import-time side effects. |
| NFR-7 | Testability: deterministic tests for all core logic without network; live tests opt-in and separated. |
| NFR-8 | Performance: bounded concurrency (1–16 cases), predictable local resource use; no external infrastructure. |

## 5. User workflows

1. **First run (no key):** install → `tracegrade evaluate` or UI *New evaluation* →
   results → inspect a case.
2. **Real model evaluation:** add key to `.env` → `doctor` → evaluate with agent and judge
   → inspect failures, read judge reasons → change prompt/model → evaluate → compare.
3. **Dataset authoring:** download the bundled dataset as a template → edit → validate →
   upload or `--dataset path` → evaluate.
4. **CI gate:** `tracegrade evaluate --suite deterministic --fail-on-failure`.
5. **Exploration:** agent playground conversation with tool-call display.

## 6. Data inputs and outputs

* **Inputs:** dataset JSON (≤ 1 MB by default); environment configuration; for real
  providers, network access and an API key.
* **Outputs:** `runs/<run_id>.json` (see schema in the book), exports (JSON, CSV,
  Markdown), logs (stderr, optional file), uploaded datasets in `datasets/`.

## 7. Evaluation methodology (summary)

The agent executes each case once in isolation. Deterministic metrics compare recorded
facts with explicit expectations. DeepEval metrics send the case input, answer, tool calls
and (for agentic metrics) the recorded trace to a judge model. Scores are in [0, 1];
thresholds turn them into pass/fail; aggregation never mixes metrics. Full details,
formulas and limitations: project book Part V.

## 8. Acceptance criteria

| ID | Criterion | Evidence |
|---|---|---|
| AC-1 | `uv sync` then `uv run tracegrade evaluate` completes offline with 16/16 cases passing every deterministic metric. | Verification report §3 |
| AC-2 | The `naive` offline variant in `prompt_only` mode fails `refund_outcome` on exactly the five cases with ineligible requested items. | `test_naive_agent_without_guardrails_is_caught` |
| AC-3 | Every `expected_refund_total` in the bundled dataset equals the policy code's result. | `test_bundled_expected_refunds_match_policy_oracle` |
| AC-4 | Agent errors, timeouts and tool loops are recorded per case without aborting the run. | integration tests |
| AC-5 | Judge failures are retried only when transient, bounded, and reported as errors; invalid scores are never recorded as scores. | `test_judge_metrics.py` |
| AC-6 | An interrupted run can be resumed to completion. | `test_interrupted_run_can_be_resumed` |
| AC-7 | The UI completes the principal workflow (configure → run → results) and never shows secrets. | `tests/ui/test_app.py` |
| AC-8 | All seven DeepEval metric classes run through TraceGrade's integration path (with a test-double judge). | `test_real_deepeval_metrics_run_with_fake_judge` |
| AC-9 | Static checks clean: ruff, mypy; bandit has no medium/high findings; pip-audit no known vulnerabilities. | Verification report §5 |
| AC-10 | A real-provider evaluation completes with valid judge scores. | Met on Groq (verification report §4–5); OpenAI not verified |

## 9. External dependencies

LangChain / LangGraph (agent runtime), DeepEval (judge metrics), langchain-openai,
langchain-groq, Pydantic / pydantic-settings, Streamlit, pandas, Altair. Real evaluations
need an account with Groq or OpenAI.

## 10. Exclusions and deferred features

* Multi-turn evaluation cases (the agent and playground support conversations; datasets
  are single-turn).
* Multi-user deployment, authentication, a database server, a job queue.
* Agents other than the bundled refund agent (the engine is agent-specific in
  `execution.py`; generalising is on the roadmap).
* Additional providers (the registry can be extended; only offline, Groq and OpenAI are
  implemented).
* Confident AI cloud integration and DeepEval's own test runner.
* Docker packaging (no server-side state or system dependencies justify it).

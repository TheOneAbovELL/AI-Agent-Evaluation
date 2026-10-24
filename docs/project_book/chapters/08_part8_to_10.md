# Part VIII — Testing, quality and verification

## 53. Testing architecture

Four layers (`docs/TESTING_STRATEGY.md` has the full table): **unit** (131 tests) for pure
logic and for DeepEval metric classes driven by a test-double judge; **integration** (16) for
engine + agent graph + tools + storage + CLI; **UI** (10) for the Streamlit pages via AppTest;
**live** (2, skipped by default) for real providers. The mock boundary is always the model
call: the offline model, failing/slow/looping chat models, a schema-filling DeepEval judge,
scripted metric objects and a structured-output fake. No test patches TraceGrade internals.

Isolation (`tests/conftest.py`): each test runs in a fresh temporary directory, all
`TRACEGRADE_*` variables and provider keys are removed, settings caches are cleared and the
application logger is reset; DeepEval's pytest plugin is disabled; telemetry is opted out.

## 54. Coverage of important behaviour

| Behaviour | Proven by |
|---|---|
| Policy boundaries 0/30/31/−1 days, unknown customer, duplicates, Decimal exactness | `test_records_policy.py` |
| Every bundled expected refund equals the policy result (oracle) | `test_dataset.py::test_bundled_expected_refunds_match_policy_oracle` |
| Guardrails, including cumulative ticket limit; prompt-only mode has none | `test_tools.py` |
| Offline model parsing and both variants | `test_offline_model.py` |
| Each deterministic metric incl. edge cases and heuristic phrasing | `test_deterministic_metrics.py` |
| Judge runner: retry only transient, bounded; invalid scores → error; timeout; redaction; skip rules | `test_judge_metrics.py` |
| All 7 DeepEval metric classes through TraceGrade's integration path | `test_real_deepeval_metrics_run_with_fake_judge[...]` |
| Aggregation formulas; storage atomicity, corruption, traversal; exports; CSV injection; compare | `test_results_storage_export.py` |
| Settings/.env, invalid configuration messages, redaction, offline-safe client construction, judge adapter | `test_config_providers.py` |
| End-to-end runs, guardrail effect, agent error/timeout/loop, preflight, interrupt + resume, changed dataset, engine failure | `test_engine.py` |
| CLI commands and exit codes | `test_cli.py` |
| UI pages and principal workflow | `test_app.py` |

## 55. Offline versus live verification

| Aspect | Offline (credential-free) | Live (Groq) |
|---|---|---|
| What runs | Real agent graph, tools, ledger, metrics, storage; rule-based model | Same pipeline with a real LLM agent and an LLM judge |
| Proves | Pipeline correctness, dataset consistency, metric logic, UI and CLI | Provider integration, structured output, retries, judge scoring |
| Cost and speed | Free; the whole test-suite runs in about 20–30 seconds | Token-metered; minutes per case on a low tokens-per-minute tier |
| Repeatability | Bit-for-bit | Varies with sampling and provider-side changes |
| Status | 158 tests passing, clean installs verified | See Chapter 56 and `docs/VERIFICATION_REPORT.md` |

## 56. Actual results and known untested behaviour

Full commands and outputs are in `docs/VERIFICATION_REPORT.md` (also Appendix G).

* **Offline:** 158 tests pass; coverage 89 %; ruff, mypy, bandit (low findings only) and
  pip-audit clean; clean installs with uv and pip; `python start.py` serves the UI.
* **Live agent (Groq, `qwen/qwen3.8-27b`, 16 cases):** every case completed and every refund
  outcome was correct. Three cases failed `tool_argument_match` because the model passed the
  ineligible item to `calculate_refund`; the guardrail removed it, so the money was right, but
  the procedure was not — a real finding of the kind TraceGrade exists to surface.
* **Live judge (Groq, `openai/gpt-oss-20b`, 3 cases):** all six judge metrics scored every
  case without errors. Several judge reasons were demonstrably wrong (Chapter 32).
* **Live provider bugs** found and fixed during verification are listed in Chapter 72.

Untested or unverified: the live OpenAI path, judge-cost reporting for non-OpenAI judges,
judge-score variance across repeated runs, macOS/Linux and Python 3.13, browser-initiated
stop during a UI run (same code path as cancellation, which is tested). Performance was not
benchmarked; observed timings are reported only as context (offline: well under a second of
agent time per case; live on a rate-limited tier: about 30 s per case without judges).

# Part IX — Security, privacy and operational concerns

## 57. Threat model

Assets: provider API keys (financial exposure), dataset contents (could be real customer
data in other deployments), run records, the integrity of evaluation results. Actors: the
local user (trusted), anyone who can reach the Streamlit port (untrusted if exposed), content
inside datasets and model outputs (untrusted), the LLM providers (trusted with what is sent),
the dependency supply chain.

| Threat | Mitigation | Residual risk |
|---|---|---|
| Key leakage via logs, errors, exports | `SecretStr`; redaction filter on all log records; agent/judge error messages redacted (known key formats + literal configured values); keys never part of `ModelSpec`/run records | Unknown secret formats inside third-party error text |
| Key leakage via UI | Settings shows only set/not set; test asserts the key never appears in page text or tables | — |
| Arbitrary file read via UI | No path input; only bundled datasets and the datasets folder; uploads saved under sanitised names | Anyone with UI access can read the bundled/uploaded datasets and runs |
| Path traversal via run ids | `validate_run_id` regex; tests with `../` variants | — |
| Oversized/malformed uploads | Size limit (default 1 MB), UTF-8 + JSON + schema validation, `extra="forbid"` | — |
| Spreadsheet formula injection via exported model output | CSV cells beginning with `= + - @` prefixed with `'` | Other consumers of JSON exports must treat text as untrusted |
| Prompt injection by customer messages | Prompt rule 10; dataset case `policy-override-attempt`; enforced guardrails cap refunds at eligible amounts | `prompt_only` mode intentionally has no guardrails |
| Tool-calling loops / runaway cost | Recursion limit (default 25 steps), per-case timeout, bounded retries, concurrency limit | A large dataset still costs proportionally |
| Untrusted model output executed | Never: outputs are stored and displayed (escaped), not executed | — |
| Unauthenticated UI exposure | Documented: run on localhost or behind access control | No built-in authentication |
| Telemetry | DeepEval telemetry opted out by default | User can re-enable |
| Supply chain | Locked versions (`uv.lock`), `pip-audit` clean, reputable packages only | Future advisories; re-audit on upgrade |

## 58. Secrets and configuration

Keys come only from the environment or `.env` (git-ignored; `.env.example` contains no
values). They are converted to plain strings only at the moment a client is constructed.
`check_connection` (one real call) runs only on explicit request.

## 59. External data flows

| To | What | When |
|---|---|---|
| Agent provider (Groq/OpenAI) | System prompt, customer message, tool schemas, tool results (purchase records of the named customer) | Each agent step of a real run or playground turn |
| Judge provider | Case input, agent answer, reference answer, tool calls/arguments/outputs, execution trace | Each judge metric call |
| DeepEval / Confident AI | Nothing: TraceGrade does not use DeepEval's cloud features; telemetry is off | — |
| Package indexes | Package downloads | Installation only |

With the bundled synthetic dataset no personal data is involved. With real data, obtain the
necessary authorisation before running against external providers.

## 60. Logging and retention

Logs go to stderr (and optionally `TRACEGRADE_LOG_FILE`), text or JSON, redacted. They contain
run ids, case ids, provider/model labels, error types and — at DEBUG — tool names and
arguments (customer IDs, items, amounts). Run records are kept until deleted
(`tracegrade runs delete <id> --yes` or removing files from `runs/`); there is no automatic
retention policy.

## 61. Operational failure modes

| Failure | Behaviour |
|---|---|
| Provider outage / 5xx / 429 | Client retries per call (`max_retries`); remaining failure → case `error`; judge: bounded retries → metric `error` |
| Invalid key | Case `error` with redacted 401 message; other cases continue |
| Timeout | Case `timeout`; judge metric `error` |
| Malformed judge output | Metric `error` ("invalid JSON"/"invalid score") |
| Disk full / permission | `StorageError` naming the path; run cannot be saved |
| Process killed (power loss) | Last saved state remains (`running`); resume evaluates missing cases |
| Corrupt run file | Skipped in listings with a warning; `load` reports it |

# Part X — Deployment and future maintenance

## 62. Supported deployment options

TraceGrade is a **local developer tool**. Supported: running the CLI and the Streamlit UI on a
workstation (verified on Windows 11). Running the UI on a shared server is possible
(`tracegrade ui --headless --port …`) but **not verified** and requires putting it behind an
authenticating reverse proxy. It has not been deployed anywhere.

## 63. Production-readiness checklist (for a shared deployment)

1. Authentication in front of the UI; HTTPS.
2. Separate API keys with spending limits for the deployment.
3. `TRACEGRADE_RUNS_DIR` on persistent, backed-up storage.
4. `TRACEGRADE_LOG_FORMAT=json` and `TRACEGRADE_LOG_FILE` shipped to your log system.
5. Live tests passing against the chosen provider and model.
6. A run index (roadmap) if thousands of runs are expected.

## 64. Environment-specific configuration

All configuration is environment variables (Chapter 77); use different `.env` files per
environment with `tracegrade --env-file path/to/.env …` for the CLI, or set variables in the
service environment for the UI.

## 65. Startup, shutdown, persistence and backup

Start: `tracegrade ui` or `streamlit run`. Shutdown: Ctrl+C; an in-flight UI run is marked
interrupted when Streamlit stops the script, but a hard kill leaves it `running` (resume
completes it). Back up `runs/` and `datasets/` as plain files; restoring is copying them back.

## 66. Monitoring and troubleshooting

Watch for WARNING records (`agent execution failed`, `ticket rejected`, `transient judge
failure; retrying`). `tracegrade doctor` shows configuration and provider readiness;
`--ping` checks connectivity. Chapter 52 lists common failures.

## 67. Scaling constraints

Concurrency is per process (1–16 cases; judge calls up to 3× that). Throughput is bounded by
provider rate limits. Run listing reads all run files. Evaluations of very large datasets
should use the CLI rather than the UI.

## 68. Version compatibility and upgrades

Tested with: Python 3.12.15; langchain 1.4.7, langchain-core 1.7.0, langgraph 1.2.16,
deepeval 4.3.1, langchain-openai 1.7.2, langchain-groq 1.1.3, pydantic 2.14.1,
pydantic-settings 2.16.1, streamlit 1.66.1, pandas 3.1.0, altair 6.3.0. Version ranges in
`pyproject.toml` allow minor updates; follow Chapter 51 when upgrading. Run records carry
`schema_version: 1`; a future incompatible change should bump it and add a migration in
`RunStore.load`.

## 69. Maintenance procedures

* Monthly: `uv lock --upgrade`, full tests, `pip-audit`, live tests.
* When a provider retires a model: update `DEFAULT_AGENT_MODELS` / `DEFAULT_JUDGE_MODELS`,
  `.env.example`, README and this book.
* When editing the dataset: run the oracle test; bump the dataset `name` (e.g. `_v2`) if
  semantics change, so runs remain comparable by hash and name.
* When editing the prompt: note that the prompt fingerprint changes and comparisons will warn.

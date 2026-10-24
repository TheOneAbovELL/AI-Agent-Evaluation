# Testing strategy

## Goals

1. Prove the **evaluation logic is correct** (policy, metrics, aggregation) with exact,
   deterministic tests.
2. Prove the **integration paths work** — the real LangGraph agent, the real tools, the real
   DeepEval metric classes, storage, CLI and UI — without network access or cost.
3. Exercise **failure modes** deliberately: provider errors, timeouts, tool loops, malformed
   or out-of-range judge output, transient vs. permanent errors, interruption and resume,
   corrupt files, path traversal, secrets.
4. Keep **live provider tests** separate, opt-in and explicit about what they prove.

## Test layers

| Layer | Location | Tests | What is real | What is replaced |
|---|---|---:|---|---|
| Unit | `tests/unit/` | 131 | All TraceGrade code under test; DeepEval metric classes in `test_judge_metrics.py` | LLMs (offline model, `SchemaFillingJudge`, `FakeMetric`) |
| Integration | `tests/integration/` | 16 | Engine + agent graph + tools + metrics + run store + CLI (in-process and one subprocess) | LLMs (offline model, failing/slow/looping fake chat models, fake judge) |
| UI | `tests/ui/` | 10 | The Streamlit app and pages, driven by `streamlit.testing.v1.AppTest` | LLMs (offline model) |
| Live | `tests/live/` | 2 | Everything, including Groq/OpenAI APIs | Nothing; skipped unless `TRACEGRADE_RUN_LIVE_TESTS=1` and the key is set |

Counts are from `pytest --collect-only` (parametrised cases counted individually).

## Test doubles and mock boundaries

* **`OfflinePolicyChatModel`** (production code, offline provider): drives the real agent
  graph and tools deterministically. Used as the default agent in tests.
* **`FailingChatModel` / `SlowChatModel` / `LoopingChatModel`** (`tests/conftest.py`):
  simulate a 401 with a key-like string in the message, a hang, and an endless tool loop.
* **`SchemaFillingJudge`** (`tests/fakes.py`): a `DeepEvalBaseLLM` that answers every
  schema request with a valid instance. It lets the *actual* DeepEval metric classes run
  through TraceGrade's integration code. Its scores are meaningless by construction and
  are only used to check plumbing (score range, status mapping, that the judge is or is
  not called).
* **`FakeMetric`** (`tests/unit/test_judge_metrics.py`): scripted `a_measure` behaviour to
  test retries, timeouts, invalid scores and redaction in `run_judge_metric`.
* **`StructuredFake`**: a LangChain fake chat model to test the judge adapter's structured
  output and its raw-text fallback.

The boundary is always the model call. No test patches TraceGrade's own functions.

## Isolation

`tests/conftest.py` makes every test run in a fresh temporary working directory, removes
`TRACEGRADE_*`, `OPENAI_API_KEY` and `GROQ_API_KEY` from the environment, clears the
cached settings and resets the application logger afterwards. A developer's `.env` and real
keys therefore cannot influence or be spent by the default test run. DeepEval's pytest
plugin is disabled (`-p no:deepeval`) and its telemetry is opted out.

## Coverage of important behaviour

| Area | Key tests |
|---|---|
| Policy boundaries (0, 30, 31 days, future, unknown, duplicates, Decimal sums) | `test_records_policy.py` |
| Dataset ↔ policy consistency (oracle) | `test_bundled_expected_refunds_match_policy_oracle` |
| Tool guardrails incl. cumulative ticket limit | `test_tools.py` |
| Offline model parsing and behaviour | `test_offline_model.py` |
| Every deterministic metric, normalisation, LCS, heuristic phrasing | `test_deterministic_metrics.py` |
| Judge runner: pass/fail, invalid scores, transient retry, bounded retry, permanent error, timeout, redaction, skip rules | `test_judge_metrics.py` |
| All 7 DeepEval metric classes through the integration path | `test_real_deepeval_metrics_run_with_fake_judge` |
| Aggregation formulas, case status rules | `test_results_storage_export.py` |
| Atomic storage, corrupt files, path traversal, exports, CSV injection, compare | `test_results_storage_export.py` |
| Settings, `.env`, blank keys, invalid config messages, redaction, provider construction without network | `test_config_providers.py` |
| Engine end to end, guardrails vs. no guardrails, agent errors, timeout, recursion limit, preflight, interruption + resume, changed dataset, unexpected exception | `test_engine.py` |
| CLI commands, exit codes, readable errors, module entry point | `test_cli.py` |
| UI pages incl. running an evaluation, provider gating, `$` escaping, playground chat, secrets not displayed | `test_app.py` |

## Known untested behaviour

* Real provider responses (rate-limit headers, provider-specific structured output
  quirks) — covered by the opt-in live tests and the live runs in the verification report
  for Groq; not verified for OpenAI (no key).
* Streamlit page code is executed by `AppTest` but not attributed by `coverage.py`; the
  coverage figure therefore excludes `ui/app.py` and `ui/pages/*` and under-reports
  `ui/state.py`.
* The interactive `tracegrade chat` loop (reads stdin) and `tracegrade ui` (spawns
  Streamlit) are not automated; both were exercised manually (verification report).
* Browser stop during a UI run (Streamlit `StopException`) is handled by the same
  `BaseException` branch as Ctrl+C, which is tested via cancellation, not via a browser.

## Commands

```bash
uv run pytest                                  # everything except live (≈20 s)
uv run pytest tests/unit                       # fast unit tests
uv run pytest -m ui                            # UI tests only
uv run pytest --cov --cov-report=term          # coverage
TRACEGRADE_RUN_LIVE_TESTS=1 uv run pytest tests/live -m live -v   # real APIs, costs money
```

# Verification report — TraceGrade 1.0.0

Everything below was executed and observed on **2026-10-24** on Windows 11 Home
(10.0.26300), CPython 3.12.15 (uv-managed), uv 0.13.1, from the project root. Nothing in this
report is estimated. §8 lists what was not verified.

## 1. Summary

| Area | Result |
|---|---|
| Automated tests (offline) | **158 passed**, 0 failed |
| Live tests (`tests/live`, Groq) | Passed before the final redesign (3 cases, all metrics, 11 min); after it, two attempts failed on Groq 429 rate limits once the day's quota was spent (§8). The post-redesign live evidence is §4–5. |
| Coverage (line + branch, `coverage.py`) | **89 %** overall (Streamlit page scripts not attributed, see §2) |
| Lint / format | `ruff check`: all checks passed; `ruff format --check`: 65 files already formatted |
| Type checking | `mypy`: no issues in 45 source files |
| Security scan | `bandit`: 0 high, 0 medium, 6 low (reviewed, §6) |
| Dependency audit | `pip-audit`: no known vulnerabilities |
| One-step launcher | `python start.py` installs, checks and serves the UI; HTTP 200 after 4 s. Fresh copy without `.venv`/`.env`: `python start.py --setup-only` created `.env`, installed from `uv.lock`, and the copy's tests passed (158 passed, 2 skipped) |
| Live agent (Groq `qwen/qwen3.8-27b`, 16 cases) | 16/16 completed; **refund outcome correct in 16/16**; 13 cases passed all metrics (§4) |
| Live judge (Groq `openai/gpt-oss-20b`, 3 cases) | All 6 LLM-judge metrics scored on every case, **0 metric errors** (§5) |
| Live multi-turn chat (UI playground) | Asked for the customer ID, then refunded only the requested item |
| OpenAI provider | **Not verified live** (no key) |

## 2. Automated tests

```text
uv run pytest -p no:cacheprovider --ignore=tests/live --cov --cov-report=term
TOTAL 2513 statements, 229 missed, 668 branches, 79 partial → 89%
158 passed in 20.62s
```

Coverage per module is printed by the command above. `ui/app.py` and the page scripts run
inside Streamlit's AppTest but are not attributed by `coverage.py`, so the UI figures
under-report what the 10 UI tests exercise. Inventory: unit 131, integration 16, UI 10,
live 2 (see `docs/TESTING_STRATEGY.md`).

## 3. Offline workflow

```text
uv run tracegrade evaluate --agent-provider offline --judge-provider none
→ Cases: 16/16 finished | passed 16 | failed 0 | incomplete 0 | agent errors 0
```

Negative control (rule-based agent that skips the date check, no guardrails):

```text
uv run tracegrade evaluate --agent-provider offline --agent-model naive --policy-mode prompt_only --suite deterministic
→ passed 5 | failed 11; refund_outcome 11/16 (e.g. same-day-and-expired-items refunded $73, expected $9)
```

## 4. Live agent run (Groq)

Configuration: agent `groq:qwen/qwen3.8-27b`, temperature 0, policy mode `enforced`, no judge,
deterministic suite, concurrency 1. Run `20261024-061220-30590d`.

| Metric | Result |
|---|---|
| refund_outcome | 16/16 |
| expected_tool_coverage | 15/15 (1 not applicable) |
| forbidden_tool_avoidance | 8/8 |
| tool_order | 11/11 |
| answer_action_consistency | 16/16 |
| tool_argument_match | 12/15, mean 0.95 |
| deepeval_tool_correctness | 12/15, mean 0.975 |

Cases: 13 passed, 3 failed, 0 agent errors. Mean agent latency 30.1 s per case (rate-limited
tier); agent tokens 62,989 in / 3,491 out.

**Finding.** The three failures (`mixed-eligibility`, `same-day-and-expired-items`,
`thirty-day-boundary`) are the same behaviour: the model passed the *ineligible* item to
`calculate_refund` together with the eligible one, contrary to the prompt's procedure step 3.
The enforced guardrail removed the ineligible item, so every refund amount was still correct,
and the replies explained the refusals. This is a genuine model finding surfaced by
`tool_argument_match`; the agent was not tuned to hide it.

## 5. Live judge run (Groq)

Configuration: agent `groq:qwen/qwen3.8-27b`, judge `groq:openai/gpt-oss-20b`, all 13 metrics,
cases `mixed-eligibility`, `quote-without-ticket`, `policy-override-attempt`. Run
`20261024-062052-e3906e`.

| Metric | Mean | Passed / evaluated |
|---|---:|---:|
| task_completion | 0.52 | 1/3 |
| step_efficiency | 0.50 | 1/3 |
| plan_quality | 0.25 | 0/3 |
| plan_adherence | 0.67 | 2/3 |
| argument_correctness | 0.64 | 0/3 |
| answer_correctness | 1.00 | 3/3 |
| deterministic metrics | refund_outcome 3/3, tool_order 3/3, tool_argument_match 2/3 | |

All six judge metrics produced a valid score on every case; no metric errored. The judge's
reasons show why judge scores must be read critically: it penalised `argument_correctness` in
the injection case because the refund "did not match the requested $300", claimed in
`task_completion` that the sticker pack had not been requested (it had), and rated the
standard one-tool-per-step loop as inefficient. The deterministic metrics and
`answer_correctness` agree that the agent behaved correctly in these cases. DeepEval did not
report a judge cost for the LangChain-adapted Groq judge (`judge_cost: n/a`).

## 6. Static analysis and security checks

| Command | Output |
|---|---|
| `uv run ruff check src tests start.py docs/project_book/build_book.py` | `All checks passed!` |
| `uv run ruff format --check …` | `65 files already formatted` |
| `uv run mypy` | `Success: no issues found in 45 source files` |
| `uv run bandit -q -r src start.py` | 6 × LOW: B404/B603 in `cli.py` and `start.py` (subprocess with fixed argument lists, no shell); B311 in `judge.py` (`random` for retry jitter) |
| `uv run pip-audit` | `No known vulnerabilities found` |

## 7. Live integration findings fixed during verification

| Symptom (live only) | Fix |
|---|---|
| Groq 400 "json mode cannot be combined with tool/function calling" | Response-tool strategy for all non-OpenAI models |
| Groq 400 `tool_use_failed`: model called the response tool by a lower-case name | Response tool named `reply` |
| Groq 429 on an 8,000 tokens/minute tier | Model-call retry middleware with backoff; 4 retries, 300 s case timeout by default |
| Groq 400 "Tool choice is required, but model did not call a tool" after a ticket was issued | Groq client relaxes forced tool choice to `auto`; prompt asks to finish with `reply` |
| Groq 400 `output_parse_failed` with `gpt-oss-120b` as agent (reasoning leaked) | Retryable; model comparison on 4 cases: `qwen/qwen3.8-27b` 4/4, `gpt-oss-120b` 1/4 → Qwen is the default Groq agent |
| Judge structured output failing with LangChain's default method | `json_schema` method for the Groq judge |
| 429 "tokens per day" quota exhausted during diagnostics | Daily-quota errors are not retried (fail fast with the provider message) |

## 8. Not verified

| Item | Exact procedure |
|---|---|
| OpenAI agent + DeepEval native OpenAI judge | Set `OPENAI_API_KEY`; `uv run tracegrade evaluate --agent-provider openai --judge-provider openai` |
| Default Groq judge `openai/gpt-oss-120b` on a full run | Its daily quota was exhausted by diagnostics on the verification day; repeat `uv run tracegrade evaluate --concurrency 1` on another day |
| `tests/live` on the final code | Both final attempts hit Groq 429: the first during judge calls (agent and judge on the same model), the second immediately and non-retried as a daily-quota error after the day's runs. Repeat `TRACEGRADE_RUN_LIVE_TESTS=1 uv run pytest tests/live -m live -v` on a fresh quota day (the test now uses the provider's default judge, a different model from the agent) |
| Judge-score variance across repeated runs | Run the same evaluation several times and compare with `tracegrade runs compare` |
| macOS / Linux, Python 3.13 | `python start.py --setup-only && uv run pytest` |

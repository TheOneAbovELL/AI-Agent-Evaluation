# Verification report — TraceGrade 1.0.0

Everything below was executed and observed on **2026-10-23/24** on Windows 11 Home
(10.0.26300), CPython 3.12.15 (uv-managed), uv 0.13.1, from the project root unless stated.
Nothing in this report is estimated. Items that could not be verified are listed in §7.

## 1. Summary

| Area | Result |
|---|---|
| Automated tests | **157 passed, 2 skipped** (live tests, opt-in) — 0 failed |
| Coverage (line + branch, `coverage.py`) | **89 %** overall (UI page scripts not attributed, see §2) |
| Lint / format | `ruff check`: all checks passed; `ruff format --check`: 63 files already formatted |
| Type checking | `mypy`: no issues in 45 source files |
| Security scan | `bandit`: 0 high, 0 medium, 3 low (reviewed, §5) |
| Dependency audit | `pip-audit`: no known vulnerabilities |
| Clean install, uv | Fresh copy, `uv sync --locked` → tests 157 passed / 2 skipped → offline evaluation 16/16 |
| Clean install, pip | Fresh venv, `pip install -r requirements.txt` + `pip install -e . --no-deps` → evaluation 16/16, `doctor` OK |
| CLI workflows | evaluate, runs list/show/export/compare/delete, dataset, metrics, doctor, resume (tests + manual) |
| UI workflows | All 7 pages exercised in a browser and by AppTest; evaluation run from the UI |
| Live LLM providers | **Not verified** (no permitted API key; see §7) |

## 2. Automated tests

Command:

```text
uv run pytest -p no:cacheprovider --cov --cov-report=term
```

Result (final run, 2026-10-23T18:32Z):

```text
157 passed, 2 skipped in 30.65s
SKIPPED [2] tests\live\test_live_providers.py:45: set TRACEGRADE_RUN_LIVE_TESTS=1
TOTAL  2482 statements, 226 missed, 658 branches, 79 partial  →  89%
```

Per-module coverage highlights: `aggregate.py`, `models.py`, `policy.py`, `agent.py` 100 %;
`tools.py` 98 %; `dataset.py` 98 %; `deterministic.py` 96 %; `judge.py` 96 %; `offline.py`
96 %; `engine.py` 94 %; `cli.py` 74 % (`chat` and `ui` commands are interactive);
`ui/state.py` 56 % and `ui/app.py` 0 % — Streamlit page scripts execute inside AppTest but
are not attributed by `coverage.py`, so these figures under-report UI testing.

Test inventory (from `pytest --collect-only`, 159 collected): unit 131, integration 16,
UI 10, live 2. See `docs/TESTING_STRATEGY.md`.

## 3. Principal workflow (offline)

```text
uv run tracegrade evaluate
```

Observed: run completed; `Cases: 16/16 finished | passed 16 | failed 0 | incomplete 0 |
agent errors 0`; all seven no-judge metrics 100 % on evaluated cases; the six LLM-judge
metrics reported as *skipped* on all 16 cases (no judge configured); run saved to
`runs/<run_id>.json`.

Negative control:

```text
uv run tracegrade evaluate --agent-model naive --policy-mode prompt_only --suite deterministic
```

Observed: `passed 5 | failed 11`; `refund_outcome` 11/16 (fails exactly on
`outside-refund-window`, `mixed-eligibility`, `same-day-and-expired-items`,
`future-dated-purchase`, `thirty-day-boundary`); `tool_order` 0/11. This shows the metrics
detect a policy-violating agent. With guardrails (`enforced`) the same naive agent's refunds
are all correct while `tool_order` still fails (asserted in
`test_guardrails_keep_naive_refunds_correct`).

## 4. UI verification

Performed in the Claude desktop browser pane against `streamlit run src/tracegrade/ui/app.py`
(Streamlit 1.66.1, 1440×900):

* New evaluation → Run evaluation with a label → 16/16 completed with live progress → Open
  results.
* Results: summary, charts, case table and case details, export tab; Compare (two runs);
  Playground: two-turn conversation (username asked, then refund of $45 with the expired item
  explained, ticket TKT-0001 shown); Datasets; Settings & help.
* Defects found and fixed during this check: UTC times without label; hidden axis labels;
  `$` amounts rendered as LaTeX; squashed charts; "credential present" for the offline
  provider. A suspected sign error on the Compare page was a screenshot-scaling artefact
  (verified with the CLI and a zoomed capture).

Automated UI tests (`tests/ui/test_app.py`, 10 tests) cover every page, running an evaluation
from the page, provider gating, `$` escaping, the playground chat and that secrets are not
displayed.

## 5. Static analysis and security checks

| Command | Output |
|---|---|
| `uv run ruff check src tests` | `All checks passed!` |
| `uv run ruff format --check src tests` | `63 files already formatted` |
| `uv run mypy` | `Success: no issues found in 45 source files` |
| `uv run bandit -q -r src` | 3 × LOW: B404/B603 `cli.py` (subprocess used by `tracegrade ui` with a fixed argument list, no shell); B311 `judge.py` (`random` used for retry jitter, not security) |
| `uv run pip-audit` | `No known vulnerabilities found` (the local `tracegrade` package itself is not on PyPI and is skipped) |

## 6. Clean-environment verification

Procedure: copy the project without `.venv`, `runs`, `datasets`, caches into
`_clean_check/{uv,pip}` (sibling folder, removed afterwards), then:

```text
# uv path
uv sync --locked            → installed from uv.lock
uv run pytest -q            → 157 passed, 2 skipped in 21.70s
uv run tracegrade evaluate --quiet   → 16/16, metric table as in §3

# pip path
uv venv --seed --python 3.12 .venv
.venv/Scripts/python -m pip install -q -r requirements.txt
.venv/Scripts/python -m pip install -q -e . --no-deps
.venv/Scripts/tracegrade evaluate --quiet --suite deterministic   → 16/16
.venv/Scripts/tracegrade doctor      → offline ready; groq/openai "key is not set"
```

Problems encountered during this verification (both resolved, details in the engineering
log): (1) a copy placed in a very deep temporary folder exceeded Windows' 260-character path
limit inside `.venv` and `openai` failed to import — an environment constraint now documented;
(2) the first copy command's `--exclude=datasets` also removed the bundled dataset folder —
fixed by anchored excludes; `resources/` was additionally made an explicit package.

## 7. Not verified

| Item | Why | Exact procedure |
|---|---|---|
| Groq agent + Groq judge | User declined paid keys during the session; Groq key to be supplied later | Add `GROQ_API_KEY` to `.env`; `uv run tracegrade doctor --ping`; `TRACEGRADE_RUN_LIVE_TESTS=1 uv run pytest tests/live -m live -v`; `uv run tracegrade evaluate --agent-provider groq --judge-provider groq` |
| OpenAI agent + DeepEval native OpenAI judge | No key | Same with `OPENAI_API_KEY` and `--agent-provider openai --judge-provider openai` |
| That `openai/gpt-oss-120b` (Groq) and `gpt-6-luna` (OpenAI) are available to the user's accounts | No key | `doctor --ping`; override `TRACEGRADE_*_MODEL` if needed |
| Real token usage / judge cost reporting | Requires live calls | Inspect a live run's summary |
| macOS / Linux | Only Windows available | `uv sync && uv run pytest` |
| Python 3.13 | Only 3.12 used (3.13 allowed by metadata) | `uv sync --python 3.13 && uv run pytest` |

## 8. Remaining risks

See `docs/engineering_log/KNOWN_ISSUES_AND_LIMITATIONS.md`. The most material: live
integrations unverified; judge-score validity; reliance on DeepEval's private `_trace_dict`
attribute (guarded by tests); no authentication in the UI.

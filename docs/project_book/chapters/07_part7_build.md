# Part VII — Build and development guide

All commands are run from the project root `tracegrade/`. They were executed on Windows 11
during verification; bash and PowerShell variants are given where they differ.

## 43. Supported environment and prerequisites

* Python **3.12 or 3.13** (`requires-python = ">=3.12,<3.14"`; `.python-version` pins 3.12,
  which uv downloads automatically if missing). Verified with CPython 3.12.15.
* **uv** ≥ 0.13 (verified with 0.13.1) — recommended. Alternatively pip ≥ 24.
* Network access for installation; for real evaluations, access to Groq or OpenAI.
* Windows: keep the project path reasonably short (see the path-length entry in Chapter 52).

## 44. Installation from scratch (recommended path)

**One step.** From the project folder:

```bash
python start.py
```

`start.py` creates `.env` from `.env.example` if needed, installs the locked dependencies (with
uv if it is installed, otherwise into `.venv` with pip from `requirements.txt`; repeat starts
skip unchanged installs), prints the configuration/provider check, starts the web interface
on the first free port from 8501 and opens it in the browser. Options: `--port`,
`--no-browser`, `--setup-only`. The steps below are what it does, for manual control.


```bash
cd tracegrade
uv sync
```

`uv sync` creates `.venv/`, installs the exact versions from `uv.lock` (runtime + dev group)
and installs TraceGrade itself in editable mode. Use `uv sync --locked` to fail instead of
updating the lock if `pyproject.toml` and `uv.lock` disagree (what CI should do), and
`uv sync --no-dev` for a runtime-only environment.

**Alternative: pip.**

```bash
python -m venv .venv
.venv\Scripts\activate             # PowerShell / cmd
source .venv/bin/activate          # bash
pip install -r requirements.txt
pip install -e . --no-deps
```

`requirements.txt` is generated from the lock: `uv export --no-hashes --no-dev
--no-emit-project --format requirements-txt -o requirements.txt`
(`requirements-dev.txt` likewise with `--only-group dev`).

## 45. Configuration and API keys

```bash
cp .env.example .env                 # bash
Copy-Item .env.example .env          # PowerShell
```

Edit `.env`: set `GROQ_API_KEY` (and/or `OPENAI_API_KEY`) and choose providers, e.g.
`TRACEGRADE_AGENT_PROVIDER=groq`, `TRACEGRADE_JUDGE_PROVIDER=groq`. `.env` is read from the
**current working directory**; it is git-ignored. Check with:

```bash
uv run tracegrade doctor
uv run tracegrade doctor --ping      # one tiny real request per configured model
```

## 46. Dataset setup

Nothing to do for the bundled dataset. For your own: `uv run tracegrade dataset validate
my.json`, then pass `--dataset my.json`, or put it in `datasets/` (or upload it in the UI) to
select it in the UI.

## 47. Running the application

```bash
python start.py                     # everything in one step (recommended)
uv run tracegrade ui                 # http://localhost:8501
uv run tracegrade ui --port 8600 --headless
uv run streamlit run src/tracegrade/ui/app.py    # equivalent, uses .streamlit/config.toml
uv run tracegrade chat               # terminal conversation with the agent
```

Stop the UI with Ctrl+C in its terminal.

## 48. Running an example evaluation

```bash
uv run tracegrade evaluate                                   # offline, all metrics
uv run tracegrade evaluate --suite deterministic --label baseline
uv run tracegrade evaluate --agent-model naive --policy-mode prompt_only --suite deterministic
uv run tracegrade runs list
uv run tracegrade runs compare <baseline_id> <candidate_id>
```

Expected (verified): the first two complete with 16/16 cases passed; the third shows 5 passed,
11 failed, with `refund_outcome` failing on the five cases that request an ineligible item.

With Groq (requires a key; verified on 2026-10-24, see the verification report):

```bash
uv run tracegrade evaluate --agent-provider groq --judge-provider groq --cases refund-two-eligible-items,unknown-customer
```

## 49. Inspecting and exporting results

* UI: *Run results* → tabs Summary, Cases, Export, History.
* CLI: `tracegrade runs show <id>` prints the summary plus failed/errored metrics per case;
  `tracegrade runs export <id> --format json|csv|cases-csv|md --output <file>`.
* Raw: `runs/<id>.json` (schema in Chapter 80).

## 50. Running tests and quality checks

```bash
uv run pytest                                  # 158 tests + 2 skipped live tests
uv run pytest tests/unit -q
uv run pytest -m ui
uv run pytest --cov --cov-report=term
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run bandit -q -r src
uv run pip-audit
```

Live tests (real API calls, small cost):

```bash
TRACEGRADE_RUN_LIVE_TESTS=1 uv run pytest tests/live -m live -v            # bash
$env:TRACEGRADE_RUN_LIVE_TESTS="1"; uv run pytest tests/live -m live -v    # PowerShell
```

Rebuild this book:

```bash
uv run --group docs python docs/project_book/build_book.py
```

## 51. Updating dependencies safely

1. `uv lock --upgrade-package <name>` (or `uv lock --upgrade` for everything).
2. `uv sync`, then run the full test-suite. The DeepEval integration tests
   (`test_real_deepeval_metrics_run_with_fake_judge`, trace attachment) detect breaking
   changes in DeepEval's metric API or the private `_trace_dict` attribute.
3. Run `uv run pip-audit` and re-export `requirements*.txt`.
4. Run one offline evaluation and, if keys are available, the live tests.

## 52. Troubleshooting common failures

| Symptom | Cause | Fix |
|---|---|---|
| `error: Agent model: Provider 'groq' needs GROQ_API_KEY` | Key not set in the working directory's `.env` | Add it; run from the folder containing `.env` or pass `--env-file` |
| `TRACEGRADE_AGENT_PROVIDER: must be one of …` | Typo in `.env` | Fix the value |
| `ModuleNotFoundError: No module named 'openai.types.responses…'` on Windows | Path longer than 260 characters inside `.venv` | Move the project to a shorter path or enable Windows long paths; recreate `.venv` |
| Case status `error`, "Error code: 401" | Invalid key | Replace the key |
| Many `timeout` cases | Slow provider or low timeout | Raise `TRACEGRADE_AGENT_TIMEOUT_SECONDS`, lower concurrency |
| "exceeded the recursion limit" | Model looping on tools | Inspect the trace; raise `TRACEGRADE_AGENT_RECURSION_LIMIT` only if the loop is legitimate |
| Judge metrics `error: invalid JSON` | Weak judge model | Use a stronger judge model |
| All judge metrics `skipped` | No judge configured | `--judge-provider groq` or set `TRACEGRADE_JUDGE_PROVIDER` |
| Run `interrupted` | Ctrl+C / UI stop | `tracegrade resume <id>` |
| Unexpected refusals | "Today" is the dataset reference date | Check the reference date (Datasets page) |
| Slow installs in OneDrive | Sync of `.venv` | Exclude `.venv` from sync or set `UV_PROJECT_ENVIRONMENT` |

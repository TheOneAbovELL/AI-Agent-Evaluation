# Build and run log

Commands actually executed during development, in order, with outcomes. Paths are relative
to the workspace folder `AI Agent Evaluation/` unless they start inside `tracegrade/`.
No credentials were used or printed (only the presence of keys was checked).

| # | Purpose | Command (summarised) | Environment | Outcome |
|---|---|---|---|---|
| 1 | Inventory tooling | `python --version`, `uv --version`, key presence check | Windows 11, PowerShell | Python 3.13.3, uv 0.13.1; no OpenAI key; Anthropic key present (not used, per user) |
| 2 | Extract reference | `Expand-Archive … -DestinationPath _original_extract` | | 37 files extracted, unchanged |
| 3 | Baseline env | `uv sync --locked` in `_baseline_env/` | Python 3.12.15 downloaded by uv | Success (deepeval 4.2.8, langchain 1.4.4) |
| 4 | Baseline checks | compileall; `import agent`; direct tool calls; console script; `eval_all.py`; README paths | baseline env | See discovery doc §9: import fails without key; −500 ticket accepted; entry point ImportError; README files missing |
| 5 | DeepEval internals | read sources; prototype scripted model + `CallbackHandler` | baseline env | Structured response OK; trace manager empty afterwards |
| 6 | New project deps | `uv lock`; `uv sync` in `tracegrade/` | | 143 packages; ran >10 min in background (OneDrive folder); success |
| 7 | Offline agent smoke test | python one-off over 16 cases | | 16/16 refund totals correct |
| 8 | ToolCorrectness without key | python one-off | | `DeepEvalError: OpenAI API key is not configured` → guard model approach works |
| 9 | Engine smoke test | `EvaluationEngine.run_sync` reference + naive | | reference 16/16; naive 5 passed / 11 failed on process metrics |
| 10 | CLI | `tracegrade doctor`; `tracegrade evaluate --suite deterministic --agent-model naive --policy-mode prompt_only` | | exit 0; refund_outcome 11/16 |
| 11 | UI | preview server `uv --directory tracegrade run streamlit run src/tracegrade/ui/app.py --server.port 8765` | browser pane | Workflow OK; 5 UI defects found and fixed; server restarted after shared-module edits |
| 12 | Unit tests (first) | `uv run pytest tests/unit` | | 81 passed |
| 13 | Judge probe | all 7 DeepEval metrics with fake judge | | all scored; plan metrics 1.0 with "no plans" |
| 14 | Full tests | `uv run pytest` | | failures found: cumulative guardrail gap, lost tool calls on error, logging handler on closed stream, test assertions → fixed; then 155 passed |
| 15 | Lint/format | `uv run ruff format`, `uv run ruff check --fix` | | 34 files reformatted; 19 manual fixes |
| 16 | Types | `uv run mypy` | | 46 errors → 0 |
| 17 | Security | `uv run bandit -q -r src`; `uv run pip-audit` | | 4 low → 3 low (assert removed); no vulnerabilities |
| 18 | Requirements export | `uv export --no-hashes --no-dev --no-emit-project --format requirements-txt -o requirements.txt` (+ dev) | | 385/100 lines |
| 19 | Clean install #1 | copy to session temp folder; `uv sync --locked`; pytest | | **Failed**: `openai` import error — path 265 chars > 260 (Windows limit) |
| 20 | Clean install #2 | copy to `_clean_check/`; uv + pip paths | | **Failed**: bundled dataset missing — copy excluded `datasets` everywhere; pip path otherwise worked |
| 21 | Clean install #3 | anchored excludes; uv + pip paths | | uv: 157 passed / 2 skipped, evaluation 16/16; pip: evaluation 16/16, doctor OK |
| 22 | Final verification | `uv run pytest --cov`; ruff; format check; mypy; bandit; pip-audit | | 157 passed, 2 skipped; 89 %; all clean (3 low bandit) |
| 23 | Book build | `uv run --group docs python docs/project_book/build_book.py` | Chrome 155 headless | First attempt with Edge: dump-dom empty (launcher hands off) → switched to Chrome; 2 diagrams failed (`;` in messages) → fixed; final: MD/HTML/PDF/DOCX, 8/8 diagrams |
| 24 | Appendix example | `tracegrade evaluate --cases mixed-eligibility,quote-without-ticket,missing-username` (runs dir in session temp) | | run `20261024-001246-7178b2`, 3/3 passed; used in book Appendix D |

Resolution notes for failures are in `MASTER_ENGINEERING_LOG.md` §9 and §12.

## 2026-10-24 — live verification and redesign

| # | Purpose | Command (summarised) | Outcome |
|---|---|---|---|
| 25 | Groq connectivity | `tracegrade doctor --ping` | `pong` from `openai/gpt-oss-120b` |
| 26 | Live tests (first) | `TRACEGRADE_RUN_LIVE_TESTS=1 pytest tests/live -m live` | Failed: 400 JSON mode + tools → fixed (D-28) |
| 27 | Live tests (second) | same | Failed: judge structured output, 429 TPM, lower-case tool name → fixed |
| 28 | Live tests (third) | same | **Passed** (3 cases, all metrics, 11 min) |
| 29 | Redesign | renames, new prompt and dataset, tests | 158 offline tests pass |
| 30 | Launcher | `python start.py --setup-only`; `python start.py --no-browser --port 8790` | Setup OK; HTTP 200 after 4 s; stopped |
| 31 | Live diagnosis | 3–4 case runs with gpt-oss-120b | 400 "Tool choice is required" → Groq client fix; `output_parse_failed` |
| 32 | Model comparison | 4 cases each | qwen3.8-27b 4/4; gpt-oss-120b 1/4 → Qwen default agent (D-31) |
| 33 | Full live run (aborted) | 16 cases, gpt-oss-120b judge | 429 tokens-per-day quota exhausted → stopped; daily quotas made non-retryable |
| 34 | Live agent run | 16 cases, deterministic suite | 16/16 completed, refund outcome 16/16, 13 passed, 3 argument-match failures |
| 35 | Live judge run | 3 cases, gpt-oss-20b judge, all metrics | All judge metrics scored, 0 errors |
| 36 | Offline final | pytest --cov, ruff, mypy, bandit, pip-audit | 158 passed, 89 %, clean |
| 37 | Book | `build_book.py` | MD/HTML/PDF (130 pages)/DOCX, 7/7 diagrams |
| 38 | Workspace | deleted `_original_extract/`, `_baseline_env/` | Done |

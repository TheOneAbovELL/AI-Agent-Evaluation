# Project discovery and baseline

This document records the analysis of the **reference repository** that TraceGrade was
designed from, and the baseline behaviour measured before any new code was written. The
reference was supplied as a ZIP archive of a learning project about evaluating a
LangChain agent with DeepEval. It was extracted unchanged to a folder outside this project
and used only as a blueprint; TraceGrade does not import, copy or depend on it at runtime.

Analysis date: 2026-10-23. Environment: Windows 11, Python 3.12.15 (via uv 0.13.1),
reference dependencies installed from its own `uv.lock`.

## 1. Original project purpose

The reference was an educational lab: *"Build a refund support agent, trace its tool
calls, and evaluate both its answers and its behavior with seven DeepEval metrics."* It
had two tracks:

1. **Refund agent evaluation** — a LangChain `create_agent` customer-support agent with
   four tools (`get_user_purchase_history`, `get_today_date`, `calculate_right_refund`,
   `issue_refund_ticket`), an in-memory sample purchase database, a system prompt stating
   a 30-day refund policy, a set of DeepEval *goldens*, and scripts that ran the agent and
   scored it with seven DeepEval metrics.
2. **Metric fundamentals** — small stand-alone scripts that each built a one-tool
   multiplication agent to illustrate a single DeepEval metric.

Intended users: developers learning how to evaluate tool-using agents beyond final-answer
correctness (task completion, tool selection, tool arguments, planning).

## 2. Repository structure and module responsibilities

| Path | Size | Responsibility |
|---|---:|---|
| `README.md` | 18 KB | Tutorial-style documentation |
| `pyproject.toml`, `uv.lock`, `.python-version` | | Dependencies (`asyncio`, `deepeval[inspect]`, `langchain`, `langchain-openai`, `portalocker[win32]`), Python 3.12 |
| `.env.example`, `.gitignore` | | `OPENAI_API_KEY=""`; ignores `.env`, `.venv`, `__pycache__`, `.deepeval` |
| `agent/agent.py` | 1.3 KB | Builds the agent at import time; interactive `run_conversation()` loop (commented-out call) |
| `agent/tools.py` | 2.2 KB | The four `@tool` functions over the module-level `users_data` dict |
| `agent/data.py` | 2.1 KB | `users_data`: 10 customers, 22 purchases with non-ISO dates (`2026-10-5`) |
| `agent/prompts.py` | 1.5 KB | System prompt with the refund rules |
| `agent/objects.py` | 0.5 KB | `Answer(answer, conversation)` and `PurchaseItem(name)` Pydantic models |
| `agent/models.py` | 0.2 KB | `init_chat_model(model="gpt-6-luna")` at import time |
| `evaluations/dataset.py` | 4.1 KB | 7 DeepEval `Golden`s with expected outputs and expected tools (+ parameters) |
| `evaluations/eval_all.py` | 4.8 KB | Combined runner: 4 trace metrics via `evals_iterator` + 3 single-turn metrics via `evaluate()` |
| `evaluations/model.py` | 25 B | `eval_model = "gpt-6-luna"` |
| `evaluations/{task_completion,step_efficiency,plan_quality,plan_adherence,argument_correctness,tool_correctness,answer_correctness}.py` | 0.7–1.8 KB each | One script per metric, each re-running the agent |
| `understanding_metrics/*.py` (8 files) | 1–4 KB each | Multiplication-agent metric demos (hard-coded `gpt-4`, `gpt-4o`, `gpt-4o-mini`) |
| `src/langchain_agent_evaluation_system/__init__.py` | 0 B | Empty package (scaffold) |
| `screenshots/*.png` (4) | | Terminal screenshots of one past DeepEval report |

## 3. Existing execution flow

`python evaluations/eval_all.py`:

1. Imports `dataset` and `eval_model`; inserts `agent/` into `sys.path`; imports `agent`,
   which at import time loads `.env`, builds `ChatOpenAI` (`gpt-6-luna`) and compiles the
   agent with an `InMemorySaver`.
2. `dataset.evals_iterator(metrics=[TaskCompletion, StepEfficiency, PlanQuality,
   PlanAdherence])` yields each golden; the agent is invoked with DeepEval's LangChain
   `CallbackHandler`, which captures the trace that DeepEval then scores.
3. From the same response, tool calls are collected from `AIMessage.tool_calls` and an
   `LLMTestCase` is built with expected output and expected tools.
4. `evaluate(test_cases, [ArgumentCorrectness, ToolCorrectness, GEval "Answer
   Correctness"])` scores them; DeepEval prints two terminal reports.

Results existed only as terminal output (and DeepEval's optional cloud upload); nothing was
persisted locally in a reusable form.

## 4. Existing features and where they were implemented

| Feature | Location | State |
|---|---|---|
| Refund agent with 4 tools, memory, structured answer | `agent/*` | Working with an OpenAI key |
| Interactive terminal conversation | `agent/agent.py::run_conversation` | Present, call commented out |
| 7 refund goldens | `evaluations/dataset.py` | Present |
| 7-metric combined evaluation | `evaluations/eval_all.py` | Working with an OpenAI key |
| Per-metric scripts | `evaluations/*.py` | Inconsistent configuration (see §5) |
| Metric tutorials | `understanding_metrics/` | Stand-alone, hard-coded models |
| Streamlit chat demo | referenced in README as `agent/streamlit_ui.py` | **Missing** |
| Package entry point | `pyproject.toml` → `langchain_agent_evaluation_system:main` | **Broken** (no `main`) |

## 5. Incomplete or broken features (verified)

1. **README out of sync with code.** It documents `evaluations/evaluate_all.py` (file is
   `eval_all.py`), an 8-case dataset with different scenarios (the code has 7), different
   thresholds (README: argument correctness 0.90 and "tool names only"; code:
   `threshold=None` and `INPUT_PARAMETERS` comparison), and a Streamlit UI file that does
   not exist.
2. **Broken console script.** `langchain-agent-evaluation-system` raises
   `ImportError: cannot import name 'main'`.
3. **Import-time side effects.** Importing `agent` constructs the OpenAI client; without
   `OPENAI_API_KEY` every evaluation script crashes before doing anything.
4. **Non-reproducible dates.** `get_today_date` returns the machine's date while expected
   outputs are static; the README itself warns that correct policy decisions can disagree
   with the references depending on when the run happens.
5. **Policy only in the prompt; no guardrails.** `issue_refund_ticket` accepted any amount:
   baseline call `issue_refund_ticket(user="nobody", refund_amount=-500)` returned *"a
   refund ticket has been issued successfully with the amount of -500"*.
   `calculate_right_refund` summed prices regardless of dates and silently ignored unknown
   items, and returned a `dict` despite its `-> str` annotation for unknown users.
6. **Per-metric scripts diverge** from the combined runner: `argument_correctness.py`
   collects tool calls but does not pass them to the test case; each script re-runs the
   agent, so different metrics score different executions.
7. **Structured-response tool counted as a tool call.** Tool calls were collected from all
   AI messages; with models that use LangChain's tool strategy for structured output, the
   `Answer` pseudo-tool would be counted as a tool the agent "called".
8. **No persistence, history, comparison or export** of results beyond terminal output.
9. **Unneeded / risky dependencies.** `asyncio>=4.0.0` (a PyPI placeholder shadowing a
   standard-library module name) and `portalocker` (already a DeepEval dependency).
   `deepeval[inspect]` adds a terminal UI not used by the scripts.
10. **No tests** of any kind.
11. **Telemetry.** DeepEval sends anonymous telemetry by default; the project did not opt
    out or mention it.

## 6. Architectural strengths and weaknesses

Strengths worth keeping:

* A realistic, compact business scenario where outcome, process and policy can all be
  checked.
* Evaluating both the *answer* and the *trajectory* (tools, arguments, plan) of an agent.
* Running the agent once and reusing the execution for several metrics (in `eval_all.py`).
* Expected tools with parameters in the dataset, enabling argument checks.
* A structured `Answer` with a `conversation` flag for multi-turn use.

Weaknesses:

* Scripts rather than a product: `sys.path` manipulation, import-time side effects, no
  configuration layer, no error handling, no reproducibility controls.
* Every metric depends on a paid LLM; there was no credential-free path at all.
* Ground truth was expressed only in natural language (`expected_output`) and judged by an
  LLM; the actual side effect (was a ticket issued, for how much?) was never checked
  directly.

## 7. Dependency and compatibility risks

* LangChain 1.x / LangGraph 1.x / DeepEval 4.x move quickly; DeepEval's internal trace
  format and evaluation loop are not stable public API. (TraceGrade avoids depending on
  DeepEval's tracing internals — see the decision register.)
* `gpt-6-luna` is listed in DeepEval 4.2.8's model table, but availability depends on the
  account.
* `uv_build>=0.12.22,<0.13.0` build backend pin.

## 8. Security and reliability concerns

* API key handling relied on `.env` only; nothing prevented keys appearing in logs or
  tracebacks.
* No bound on agent steps beyond LangGraph's default; no timeouts; no retry policy for
  judge calls; a single failure aborted a whole evaluation.
* Prompt injection was not considered in the dataset or the prompt.
* Refund amounts were never validated server-side (see §5.5).

## 9. Baseline test and runtime results

The reference's locked environment was installed in a separate copy (`uv sync --locked`:
success, Python 3.12.15, deepeval 4.2.8, langchain 1.4.4, langgraph 1.2.14). Commands and
observed results:

| Check | Command | Result |
|---|---|---|
| Byte-compile everything | `python -m compileall -q agent evaluations understanding_metrics src` | OK |
| Import the agent without a key | `python -c "import agent"` (in `agent/`) | **Fails**: `openai.OpenAIError: Missing credentials` |
| Tools, direct calls | `get_user_purchase_history`, `calculate_right_refund`, `issue_refund_ticket`, `get_today_date` | Work; `issue_refund_ticket("nobody", -500)` "succeeds"; date = machine date (2026-10-23) |
| Console script | `langchain-agent-evaluation-system` | **Fails**: `ImportError: cannot import name 'main'` |
| Combined evaluation without key | `python evaluations/eval_all.py` | **Fails** at import: missing OpenAI credentials |
| README command | `python evaluations/evaluate_all.py` | **Fails**: file does not exist |
| README UI | `agent/streamlit_ui.py` | **Missing** |
| Test suite | – | None exists |

No OpenAI key was available, so no LLM-backed baseline scores could be produced. The
reference README shows one historical run (task completion 0.92 avg, plan quality 0.28,
argument correctness 0.62, tool correctness 0.77, answer correctness 0.51 over 8 cases);
those figures come from a different dataset version and a different date and are **not**
reproducible baselines.

## 10. Gaps between the reference and a usable product

* No way to run anything without a paid key.
* No reproducibility (moving "today", no recorded configuration).
* No ground-truth check of the agent's side effects.
* No persistence, history, comparison or export.
* No user interface (the documented one did not exist).
* No error handling, timeouts, retries, partial-failure handling or resumption.
* No tests, no type checking, no linting.
* Documentation that contradicted the code.

## 11. Recommended target architecture (adopted)

A single installable package with clear layers (detailed in the project book):

```text
config / errors / logging
refund/        system under test (records, deterministic policy, tools + ledger, prompt, agent)
providers/     provider registry, offline reference model, judge adapter
evaluation/    dataset schema, execution + trace recording, metrics (deterministic + DeepEval),
               engine (orchestration), aggregation, file-based run store, export, compare
cli.py, ui/    two front ends over the same engine
```

## 12. Prioritised roadmap (as executed)

1. Deterministic refund policy + dataset oracle; fixed reference date. *(correctness)*
2. Tools with a ledger and optional guardrails. *(ground truth for side effects)*
3. Provider registry with a credential-free offline model. *(usable without keys)*
4. Own trace recorder; DeepEval metrics called directly with timeouts and retries.
5. Deterministic metrics.
6. Engine with bounded concurrency, incremental persistence, interruption and resume.
7. CLI, then Streamlit UI.
8. Tests (unit, integration, UI, opt-in live), static analysis.
9. Documentation, engineering log, book.

## 13. Assumptions and unresolved uncertainties

* **Assumption:** the 30-day rule means `0 <= age_days <= 30` (a purchase exactly 30 days
  old is refundable). The reference prompt says "no refund can be issued after 30 days",
  which supports this reading but is not unambiguous.
* **Assumption:** the reference README's 8-case table describes an older/newer dataset
  revision; the code's data was treated as authoritative and both sets of scenarios were
  folded into a new 16-case dataset consistent with that data.
* **Uncertainty:** which provider and model the user will finally evaluate. OpenAI
  (original) and Groq (requested by the user, key to be supplied) are implemented.
* **Uncertainty:** licence. The reference repository contains no licence file. TraceGrade
  reuses no reference source code; it does reuse the synthetic sample purchase records and
  several scenario sentences (see the decision register, D-14).

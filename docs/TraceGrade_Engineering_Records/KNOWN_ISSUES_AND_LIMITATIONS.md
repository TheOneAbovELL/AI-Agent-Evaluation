# Known issues and limitations

Status as of the 1.0.0 handover (updated 2026-10-24 after live Groq verification and the redesign). "Unverified" means implemented and tested with test
doubles, but not executed against the real service.

## Unverified integrations

| Item | Status | How to verify |
|---|---|---|
| Groq agent (`ChatGroq`) end to end | **Unverified** — no key available | Put `GROQ_API_KEY` in `.env`; `uv run tracegrade doctor --ping`; `uv run tracegrade evaluate --agent-provider groq --cases refund-two-eligible-items` |
| Groq judge via `LangChainJudgeModel` | **Unverified** live; adapter unit-tested (structured + fallback), DeepEval metrics run through the same code path with a test-double judge | `uv run tracegrade evaluate --agent-provider groq --judge-provider groq` or `TRACEGRADE_RUN_LIVE_TESTS=1 uv run pytest tests/live -m live -v` |
| Default Groq model `openai/gpt-oss-120b` | **Unverified** that it is still offered and supports tool calling + structured output on the user's account | Override with `TRACEGRADE_AGENT_MODEL` / `TRACEGRADE_JUDGE_MODEL` if needed |
| OpenAI agent and DeepEval native OpenAI judge (`gpt-6-luna`) | **Unverified** — no key | As above with `OPENAI_API_KEY` and `--agent-provider openai --judge-provider openai` |
| Token usage and judge cost figures | Only populated when the provider/DeepEval report them; never estimated | Inspect a live run |

## Methodology limitations

* **LLM-judge scores are opinions.** They vary between runs and judge models and can be
  biased (verbosity, self-preference when agent and judge are the same model family).
* **DeepEval plan metrics return 1.0 when no plan is found.** Observed while testing: when the
  judge extracts no plan from the trace, `PlanQualityMetric` and `PlanAdherenceMetric` report
  a perfect score with a reason like "There are no plans to evaluate". A high plan score
  therefore does not prove a good plan exists — read the reason.
* **DeepEval tool correctness is order-sensitive for list arguments.** `items: [book, pen]`
  vs `[pen, book]` scores 0 in DeepEval's parameter comparison. TraceGrade's own
  `tool_argument_match` normalises item lists and is the recommended argument gate.
* **DeepEval tool-correctness reasons can be misleading.** Its reason text may list a tool as
  "missing" although it was matched (observed when tool outputs are present); the score is
  correct.
* **`answer_action_consistency` is a heuristic** (regular expressions). It can misjudge
  unusual phrasing; it is labelled "heuristic" everywhere.
* **Small synthetic dataset** (16 single-turn cases). Pass rates on it have wide uncertainty
  and say nothing about other domains.
* **Single-turn cases only.** Multi-turn behaviour is available in the playground and CLI
  chat but is not evaluated.
* **The offline model is not an LLM.** Its perfect scores verify the pipeline and dataset.

## Product limitations

* The evaluation engine is specific to the bundled refund agent (`execution.py` builds it);
  evaluating a different agent requires adapting the execution layer (roadmap item).
* No authentication or multi-user isolation in the UI; run it on localhost or behind your
  own access control. Anyone with UI access can trigger paid API calls.
* Run listing reads every run file; with thousands of runs the History/Results pages slow
  down (a small index file would fix this).
* Runs cannot be deleted from the UI (CLI only, by design).
* The playground conversation is lost on page reload (kept in the Streamlit session only).
* Streamlit page modules are not attributed by `coverage.py` (they are tested via AppTest).

## Environment constraints

* **Windows path length.** The `openai` package contains files with ~110-character names.
  If the project lives under a long path, its virtual environment can exceed Windows' 260
  character limit and imports fail with `ModuleNotFoundError: No module named
  'openai.types.responses....'`. Observed when the project was copied to a deep temporary
  folder (path 265 characters); not observed at the normal project location (174
  characters). Fix: use a shorter project path or enable Windows long-path support.
* **OneDrive-synced folders.** The project currently sits in a OneDrive folder; syncing a
  `.venv` with thousands of files is slow. Consider excluding `.venv` from sync or setting
  `UV_PROJECT_ENVIRONMENT` to a local path.
* DeepEval creates an empty `.deepeval/` folder in the working directory on import; it is
  git-ignored.

## Security residual risks

* Prompt injection: the system prompt instructs the agent to ignore rule-change attempts and
  one dataset case tests it; `enforced` guardrails cap financial impact, `prompt_only` mode
  intentionally does not.
* Exported runs contain customer messages, purchase records and model outputs. They contain
  no API keys, but treat them as potentially sensitive if you use real data.
* Provider error messages are redacted for known key formats and configured key values;
  an unknown secret format inside a provider error could still appear in a run record.

## Licensing

* No licence has been chosen for TraceGrade.
* The reference repository had no licence file. TraceGrade reuses its synthetic sample
  purchase data and several short scenario sentences (no code). Confirm you have the right
  to reuse them before distributing.

## Deferred improvements (roadmap)

1. Live verification on Groq and OpenAI; record results. *(high value, low effort)*
2. Generic agent adapter interface so other LangChain agents can be evaluated. *(high/medium)*
3. Multi-turn evaluation cases. *(high/medium)*
4. Repeated runs per case with variance statistics for judge metrics. *(medium/low)*
5. Run index file for fast listing; delete/rename runs in the UI. *(low/low)*
6. Judge calibration set (human-labelled cases) to measure judge agreement. *(high/high)*


## Update 2026-10-24

* Groq agent and judge: **verified live** (see the product's verification report). The rows
  above marking Groq as unverified are superseded.
* Live finding: the Qwen agent passes ineligible items to `calculate_refund` in mixed requests;
  guardrails keep the amounts correct; `tool_argument_match` flags it.
* Live finding: small judge models (gpt-oss-20b) give demonstrably wrong reasons in some cases.
* Free-tier quotas: 8,000 tokens/minute and 200,000 tokens/day per model on Groq's on-demand
  tier; full runs with all judge metrics on 16 cases can exceed a day's quota.
* Licensing: the product no longer contains any material from the reference project (D-29).
* The Groq key was pasted into the chat transcript; rotate it if the transcript is shared.

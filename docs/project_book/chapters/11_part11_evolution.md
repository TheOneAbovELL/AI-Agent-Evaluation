# Part XI — Engineering decisions and project evolution

This part summarises how TraceGrade was built and verified, which defects were found on the
way and which approaches were abandoned.

## 70. Work completed in each phase

| Phase | Work |
|---|---|
| 1 Product definition | Problem statement, requirements, acceptance criteria, provider choice |
| 2 Core | Domain (records, policy, tools, prompt, agent), providers, evaluation engine, storage, CLI |
| 3 UI | Seven Streamlit pages, browser verification, five UI defects fixed |
| 4 Hardening | Guardrail fix, failure capture from traces, redaction, upload limits, path checks, model defaults per provider |
| 5 Testing | Unit, integration, UI and opt-in live tests; static analysis; clean-environment installs |
| 6 Live verification | Groq agent and judge; four provider-specific integration fixes (Chapter 72) |
| 7 Packaging and docs | One-step launcher `start.py`, README, configuration files, this book |

## 71. Repository contents

Every file in the repository was written for TraceGrade. The source-file index (Chapter 85)
lists them with their purpose.

## 72. Important bug fixes during development

| Bug | Found by | Fix |
|---|---|---|
| Multiple tickets could exceed the eligible quote in total | Writing a guardrail test | Compare against remaining quote |
| Tool calls lost when the agent run raised | Recursion-limit integration test | Reconstruct from trace spans + warning |
| Global logger bound to a closed test stream | Test output ("Logging error") | Reset handlers per test |
| UTC timestamps unlabelled in UI | Browser check | Local time + UTC in config panel |
| Chart labels hidden; charts squashed | Browser check | `labelOverlap=False`; explicit `height` |
| `$` amounts rendered as LaTeX | Browser check | `md()` escaping |
| Offline provider "credential present" | Browser check | "not needed" |
| Model default not matching provider | Configuration review | Provider-specific defaults |
| Groq rejected JSON mode together with tools (HTTP 400) | Live verification | Response-tool strategy for every non-OpenAI model |
| Model called the response tool by a lower-case name | Live verification | Response tool named `reply` |
| Rate limits (429) on an 8,000 tokens/minute tier | Live verification | Model-call retry middleware with backoff; higher default retries and timeout |
| Groq rejected plain-text final answers while a tool call was forced | Live verification | Groq client relaxes forced tool choice to `auto`; reply-tool instruction in the prompt |
| Reasoning text leaked into output (`output_parse_failed`) with `gpt-oss-120b` as agent | Live verification | Retryable; default Groq agent model switched to `qwen/qwen3.8-27b` |
| Groq judge structured output failed with LangChain's default method | Live verification | `json_schema` method for the Groq judge |

## 73. Behaviour worth knowing

* *Ticket for an unknown customer with a negative amount:* in `enforced` mode
  `{"status": "rejected", "reason": "unknown customer ID 'nobody'"}`; in `prompt_only` mode the
  ticket is issued, which is exactly what makes that mode useful for measuring the model.
* *Running without a key:* a full offline run, with judge metrics marked skipped.
* *A run on a different calendar day:* identical result (reference date from the dataset).

## 74. Rejected alternatives and failed approaches worth remembering

* **Using DeepEval's `CallbackHandler` to obtain traces:** the trace manager had no traces
  after the run (they are finalised and cleared). Replaced by `TraceRecorder`.
* **Constructing `ToolCorrectnessMetric` without a model:** fails without an OpenAI key.
  Solved with `NoLLMGuard`.
* **Relying on Altair `properties(height=…)` inside Streamlit 1.66:** ignored with the default
  `height="content"`; pass `height` to `st.altair_chart`.
* **Hot-reloading the UI after editing shared modules:** Streamlit reloads only page scripts;
  restart the server after changing `components.py` or engine code.
* **Clean-install test in a deep temporary folder:** exceeded Windows' path limit; use a
  normal-length path.
* **`tar --exclude=datasets`:** also excluded `src/tracegrade/resources/datasets`; anchor
  excludes (`./datasets`).

## 75. Outstanding technical debt

* Engine coupled to the refund agent (`execution.py`, ledger-specific fields).
* One private DeepEval attribute (`_trace_dict`) in use.
* `cli.py` command functions mix argument handling and presentation (74 % covered).
* No run index; listing parses every file.
* The offline model's English parsing is intentionally simple.

## 76. Roadmap (value / effort)

| # | Item | Value | Effort |
|---|---|---|---|
| 1 | Live OpenAI verification; repeat Groq runs to measure judge variance | High | Low |
| 2 | Agent adapter interface (evaluate any LangChain agent; domain-specific ledger plug-in) | High | Medium |
| 3 | Multi-turn evaluation cases | High | Medium |
| 4 | Repeated runs per case with variance and confidence intervals for judge metrics | Medium | Low |
| 5 | Judge calibration set with human labels; agreement statistics | High | High |
| 6 | Run index, delete/rename in UI | Low | Low |
| 7 | Optional authentication for shared deployments | Medium | Medium |

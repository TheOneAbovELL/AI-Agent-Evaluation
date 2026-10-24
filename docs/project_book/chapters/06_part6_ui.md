# Part VI — Frontend and user experience

## 35. Framework choice

The UI is a **Streamlit** multipage app (`st.navigation`), chosen because it keeps the whole
product in Python, renders tables and charts well, supports file upload/download and chat
natively, and can be tested headlessly with `streamlit.testing.v1.AppTest`. It calls the same
engine as the CLI; there is no separate API server and no JavaScript build. Charts use Altair
(bundled with Streamlit); tables use `st.dataframe` with column configuration.

All screenshots in this part were captured from the running application (Streamlit 1.66.1,
1440×900 viewport, downscaled) on 2026-10-24. The results screenshots show a **live** run:
the agent is `qwen/qwen3.8-27b` on Groq and the judge is `openai/gpt-oss-20b` on Groq; the
comparison screenshots show two offline runs; the playground shows a live conversation.

## 36. Navigation and page structure

| Section | Page | File |
|---|---|---|
| — | Overview | `pages/home.py` |
| Evaluate | New evaluation | `pages/evaluate.py` |
| Evaluate | Run results | `pages/results.py` |
| Evaluate | Compare runs | `pages/compare.py` |
| Explore | Agent playground | `pages/playground.py` |
| Explore | Datasets | `pages/datasets.py` |
| Help | Settings & help | `pages/settings_help.py` |

### Overview

Purpose statement, a three-step getting-started panel, provider readiness cards (checked
locally: package installed, key present — validity is only known after a call), the latest
run's summary and a recent-runs table.

![Overview page](images/01_overview.jpg)

### New evaluation

Five numbered sections: **Dataset** (bundled or datasets folder; upload with validation; case
multiselect), **Agent under test** (provider, model or offline variant, policy mode, advanced
settings: temperature, timeout, client retries, max graph steps), **LLM judge** (none, Groq,
OpenAI; model; timeout), **Metrics** (deterministic/heuristic and judge groups; threshold
editor), **Run** (label, parallel cases). Preflight runs on every change: errors disable the
button, warnings and cost/usage information are shown. During the run a progress bar and a
status box list each finished case with its status and failed metrics; at the end a link opens
the results.

![New evaluation page](images/02_new_evaluation.jpg)

### Run results

A run selector (deep-linkable with `?run=<id>`), the run title and status, an offline-model
notice when applicable, an expandable run configuration (dataset hash, models, policy mode,
prompt fingerprint, environment), and four tabs:

* **Summary** — case counts and pass rate, latency/tokens/judge cost/tickets line, metric table
  with pass-rate bars, outcomes-per-metric stacked bars, and a case × metric status grid.
* **Cases** — filterable case table (status, refunded vs. expected, tool sequence, failed
  metrics) and a case-detail panel: customer message, agent answer vs. reference, metric
  results with explanations, tool calls with arguments and outputs, tickets and rejected
  tickets, and the execution trace exactly as the judges receive it.
* **Export** — JSON, metric CSV, case CSV, Markdown downloads.
* **History** — all stored runs.

![Run results — summary](images/03_results_summary.jpg)

![Run results — charts](images/04_results_charts.jpg)

![Run results — case table](images/05_results_cases.jpg)

![Run results — case details](images/06_case_detail.jpg)

The live run shows what the two metric families are for. Every refund was correct and the
tool order was right, but in `mixed-eligibility` the model passed the expired webcam to
`calculate_refund` together with the USB hub (the guardrail removed it, so the refund was still
$25). `tool_argument_match` flags that procedural deviation exactly. The judge metrics show
mixed scores whose reasons are partly wrong — for example penalising the agent for not paying
the $300 an injected message demanded — which is why judge scores are read with their reasons
and deterministic metrics are used as gates (Chapter 32).

### Compare runs

Baseline and candidate selectors, compatibility warnings (here: different policy modes),
regression/improvement counts, a metric delta table, a grouped pass-rate chart and the
per-case status changes with the metrics that changed.

![Compare runs](images/07_compare.jpg)

![Compare runs — per-case changes](images/08_compare_cases.jpg)

### Agent playground

A multi-turn chat with the refund agent (`InMemorySaver`), configured in the sidebar (customer
data source, provider/model, policy mode, real date or reference date, *New conversation*).
Each reply shows its tool calls with arguments and JSON outputs; issued tickets are listed.
Conversations are not stored and are not evaluations.

![Agent playground](images/09_playground.jpg)

### Datasets

Case/customer counts, reference date and window, tabs for **Cases** (table, raw JSON of a case
and what the policy code decides for it), **Purchase records** (with age in days relative to
the reference date), **Schema** (field reference and template download) and **Validate a file**.

![Datasets page](images/10_datasets.jpg)

### Settings & help

Provider status table, the effective configuration (credentials shown only as set/not set),
*Reload configuration*, an opt-in **connection test** (one tiny real call per configured
model), the metric reference with interpretation guidance, troubleshooting entries and
environment information.

![Settings & help](images/11_settings.jpg)

## 37. Principal user workflows

1. *Offline first run:* New evaluation → defaults → Run evaluation → Open results → Cases tab →
   inspect a case.
2. *Real model:* add key to `.env` → Settings → Reload configuration (optionally Test) → New
   evaluation → provider Groq, judge Groq → Run → read judge reasons on failing cases.
3. *Before/after:* run A → change prompt/model → run B → Compare runs.
4. *Own dataset:* Datasets → download template → edit → New evaluation → Upload → select → Run.

## 38. Input validation and configuration in the UI

* Datasets are validated on upload (size limit, UTF-8, JSON, schema); only bundled datasets
  and files in `TRACEGRADE_DATASETS_DIR` can be selected — there is no free-form path input.
* Thresholds are constrained to [0, 1] in the editor; model names must be non-empty.
* The provider selector shows the missing-key message and the run button stays disabled until
  preflight passes.

## 39. Execution, progress, errors, empty and loading states

| State | Behaviour |
|---|---|
| No runs | Overview/Results/Compare show an explanatory info box with a link to New evaluation |
| Fewer than two runs | Compare explains that two runs are needed |
| Configuration error | Error banner with the variable name; page stops |
| Unconfigured provider | Warning under the selector; run disabled |
| Running | Progress bar + per-case status lines |
| Agent error in a case | Case line shows "agent error: …"; case detail shows the error type and message |
| Run interrupted (browser stop) | Engine marks the run interrupted; Results shows how to resume |
| Malformed upload | Error with the validation message |

## 40. Accessibility and usability

* Status is always conveyed by text (badges and table cells say "passed", "failed", …), not
  only by colour; the chart palette (green/red/orange/grey) was chosen to remain
  distinguishable for common colour-vision deficiencies, and every chart has a legend and
  tooltips.
* Data text is escaped for Markdown (`$` would otherwise turn amounts into LaTeX).
* Timestamps are shown in local time; the configuration panel also shows UTC.
* Long explanations live in wide table columns and expandable sections to keep pages
  scannable.
* Not done: a formal accessibility audit (screen-reader testing, keyboard-only navigation
  review). Streamlit's own widgets provide keyboard focus handling.

## 41. Mapping between UI actions and backend functions

| UI action | Backend |
|---|---|
| Select/upload dataset | `state.dataset_options`, `state.load_dataset` → `resolve_dataset`; `state.save_uploaded_dataset` → `parse_dataset` |
| Any configuration change | `EvaluationEngine.preflight` |
| Run evaluation | `asyncio.run(EvaluationEngine.run(request, on_event))` |
| Results / History | `RunStore.list_runs`, `RunStore.load`, `aggregate` summaries in the record |
| Download | `export.export(record, fmt)` |
| Compare | `compare.compare_runs` |
| Playground message | `build_refund_agent(..., InMemorySaver()).invoke`, `extract_tool_calls` |
| Dataset policy preview | `policy.assess_refund` |
| Provider status / Test | `registry.provider_status` / `registry.check_connection` |
| Reload configuration | `get_settings.cache_clear()` |

## 42. Known UI limitations

* Runs execute inside the Streamlit script thread: the page is busy until the run ends;
  pressing Streamlit's *Stop* interrupts the run (resumable from the CLI).
* No authentication; anyone who can open the page can start paid runs.
* No run deletion or renaming in the UI (CLI `runs delete`).
* Playground history is lost on reload.
* Streamlit re-executes the page on every interaction; very large runs (thousands of cases)
  would make the Results page slower.

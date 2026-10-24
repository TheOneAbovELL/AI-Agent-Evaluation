# File change register

TraceGrade is a new code base built in a separate directory. **Every file below was created
during this work; none was copied from the reference repository**, and the reference
repository itself was not modified. "Removed" lists reference files intentionally not
carried over (rationale: decision register D-15).

## Created — grouped by purpose

| Path | Change | Reason / functional impact | Requirement | Tests | Compatibility notes |
|---|---|---|---|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version`, `requirements.txt`, `requirements-dev.txt` | created | Packaging with hatchling; dependencies chosen for the new design; pip export | NFR-1, NFR-6 | clean-install verification | Package name `tracegrade`; CLI `tracegrade` replaces the broken reference script |
| `.env.example`, `.gitignore`, `.streamlit/config.toml` | created | Configuration template (tested valid), ignores secrets/runtime output, UI theme | NFR-5 | `test_env_example_is_a_valid_configuration` | Env names: `TRACEGRADE_*` + `OPENAI_API_KEY`, `GROQ_API_KEY` |
| `README.md` | created | User-facing documentation of the final product | all | doc audit | — |
| `src/tracegrade/{__init__,__main__,cli,config,errors,logging_utils}.py` | created | Entry points, settings, errors, logging/redaction | FR-18, NFR-3, NFR-5 | `test_cli.py`, `test_config_providers.py` | — |
| `src/tracegrade/refund/*.py` | created | System under test: records, deterministic policy, tools + ledger + guardrails, prompt, agent | FR-1–4, FR-6 | `test_records_policy.py`, `test_tools.py` | Tool and argument names kept from the reference (evaluation contract) |
| `src/tracegrade/providers/*.py` | created | Provider registry, offline model, judge adapter | FR-16 | `test_offline_model.py`, `test_config_providers.py` | — |
| `src/tracegrade/evaluation/*.py`, `metrics/*.py` | created | Dataset, execution, tracing, metrics, engine, aggregation, storage, export, compare | FR-5, FR-7–15, FR-17 | unit + integration tests | Run record `schema_version` 1 |
| `src/tracegrade/resources/datasets/refund_support_v1.json` (+ `__init__.py` files) | created | Bundled synthetic dataset (16 cases); explicit resource package | FR-21 | oracle test | Purchase values reused from reference sample data (D-14) |
| `src/tracegrade/ui/**` | created | Streamlit app (7 pages) | FR-19, FR-20 | `tests/ui/test_app.py` | — |
| `tests/**` | created | Test-suite and test doubles | NFR-7 | — | — |
| `docs/PROJECT_DISCOVERY_AND_BASELINE.md`, `PRODUCT_REQUIREMENTS.md`, `TESTING_STRATEGY.md`, `VERIFICATION_REPORT.md` | created | Required engineering documents | — | — | — |
| `docs/engineering_log/*.md` | created | Engineering records | — | — | — |
| `docs/project_book/chapters/*.md`, `build_book.py`, `images/*.jpg`, `images/diagrams/*` | created | Book sources, generator, real UI screenshots, rendered diagrams | — | build run | Diagrams regenerate when their source changes |
| `docs/project_book/PROJECT_BOOK.{md,html,pdf,docx}` | generated | Book outputs | — | — | Regenerate with `build_book.py`; do not edit by hand |

## Modified during development (notable)

| Path | Change | Reason |
|---|---|---|
| `refund/tools.py` | guardrail uses remaining quote | bug: cumulative tickets could exceed the quote |
| `evaluation/execution.py`, `tracing.py` | reconstruct tool calls from trace on failure | bug: evidence lost when the run raised |
| `evaluation/engine.py` | `BaseException` → interrupted | Streamlit stop raises a `BaseException` subclass |
| `ui/components.py`, `ui/pages/*` | local time, `$` escaping, chart heights/labels, credential label | defects found in browser verification |
| `config.py`, `providers/registry.py`, `.env.example` | model defaults per provider | configuration inconsistency |
| `refund/records.py`, `ui/components.py`, `ui/state.py` | removed unused helpers/constants | dead-code audit |

## Removed / not carried over from the reference

`agent/` (replaced by `refund/`), `evaluations/` scripts (replaced by the engine and CLI),
`understanding_metrics/` (teaching intent covered by the metric reference), the empty
`src/langchain_agent_evaluation_system` scaffold, `screenshots/`, the reference
`pyproject.toml`/`uv.lock`/`.env.example`/`.gitignore`/`README.md` (rewritten for the new
product). Dependencies dropped: `asyncio`, `portalocker` (direct), `deepeval[inspect]`.

## Generated inventory (final deliverable, excluding `.venv`, caches and runtime folders)

| File | Bytes |
|---|---:|
| `.env.example` | 2056 |
| `.gitignore` | 479 |
| `.python-version` | 5 |
| `.streamlit/config.toml` | 269 |
| `README.md` | 13857 |
| `docs/PRODUCT_REQUIREMENTS.md` | 10115 |
| `docs/PROJECT_DISCOVERY_AND_BASELINE.md` | 13434 |
| `docs/TESTING_STRATEGY.md` | 5694 |
| `docs/VERIFICATION_REPORT.md` | 7225 |
| `docs/engineering_log/BUILD_AND_RUN_LOG.md` | 4135 |
| `docs/engineering_log/DECISION_REGISTER.md` | 11070 |
| `docs/engineering_log/KNOWN_ISSUES_AND_LIMITATIONS.md` | 5826 |
| `docs/engineering_log/MASTER_ENGINEERING_LOG.md` | 7684 |
| `docs/engineering_log/PROGRESS.md` | 2426 |
| `docs/project_book/PROJECT_BOOK.docx` | 1414069 |
| `docs/project_book/PROJECT_BOOK.html` | 873671 |
| `docs/project_book/PROJECT_BOOK.md` | 292753 |
| `docs/project_book/PROJECT_BOOK.pdf` | 4662472 |
| `docs/project_book/build_book.py` | 24655 |
| `docs/project_book/chapters/00_front_matter.md` | 2331 |
| `docs/project_book/chapters/01_part1_identity.md` | 7572 |
| `docs/project_book/chapters/02_part2_reference.md` | 4815 |
| `docs/project_book/chapters/03_part3_architecture.md` | 9178 |
| `docs/project_book/chapters/04_part4_source.md` | 19566 |
| `docs/project_book/chapters/05_part5_methodology.md` | 13333 |
| `docs/project_book/chapters/06_part6_ui.md` | 8705 |
| `docs/project_book/chapters/07_part7_build.md` | 6378 |
| `docs/project_book/chapters/08_part8_to_10.md` | 11352 |
| `docs/project_book/chapters/11_part11_evolution.md` | 4641 |
| `docs/project_book/chapters/12_part12_reference.md` | 22187 |
| `docs/project_book/chapters/13_appendices.md` | 11184 |
| `docs/project_book/images/01_overview.jpg` | 35441 |
| `docs/project_book/images/02_new_evaluation.jpg` | 26385 |
| `docs/project_book/images/03_results_summary.jpg` | 35754 |
| `docs/project_book/images/04_results_charts.jpg` | 33257 |
| `docs/project_book/images/05_results_cases.jpg` | 41318 |
| `docs/project_book/images/06_case_detail.jpg` | 39976 |
| `docs/project_book/images/07_compare.jpg` | 38296 |
| `docs/project_book/images/08_compare_cases.jpg` | 42349 |
| `docs/project_book/images/09_playground.jpg` | 32819 |
| `docs/project_book/images/10_datasets.jpg` | 48345 |
| `docs/project_book/images/11_settings.jpg` | 35845 |
| `docs/project_book/images/diagrams/diagram_2684b4427118.png` | 155070 |
| `docs/project_book/images/diagrams/diagram_2684b4427118.svg` | 26683 |
| `docs/project_book/images/diagrams/diagram_2d65ce843854.png` | 70842 |
| `docs/project_book/images/diagrams/diagram_2d65ce843854.svg` | 22472 |
| `docs/project_book/images/diagrams/diagram_4b341d3cf85b.png` | 104015 |
| `docs/project_book/images/diagrams/diagram_4b341d3cf85b.svg` | 24746 |
| `docs/project_book/images/diagrams/diagram_a714b5fe33b2.png` | 81593 |
| `docs/project_book/images/diagrams/diagram_a714b5fe33b2.svg` | 32549 |
| `docs/project_book/images/diagrams/diagram_ac1540b4a95c.png` | 170660 |
| `docs/project_book/images/diagrams/diagram_ac1540b4a95c.svg` | 30964 |
| `docs/project_book/images/diagrams/diagram_dead9e10f027.png` | 195658 |
| `docs/project_book/images/diagrams/diagram_dead9e10f027.svg` | 31743 |
| `docs/project_book/images/diagrams/diagram_e04f0809e107.png` | 221718 |
| `docs/project_book/images/diagrams/diagram_e04f0809e107.svg` | 34683 |
| `docs/project_book/images/diagrams/diagram_f5b3f711e737.png` | 40801 |
| `docs/project_book/images/diagrams/diagram_f5b3f711e737.svg` | 15299 |
| `pyproject.toml` | 2257 |
| `requirements-dev.txt` | 2050 |
| `requirements.txt` | 7165 |
| `src/tracegrade/__init__.py` | 22 |
| `src/tracegrade/__main__.py` | 58 |
| `src/tracegrade/cli.py` | 21407 |
| `src/tracegrade/config.py` | 6673 |
| `src/tracegrade/errors.py` | 1384 |
| `src/tracegrade/evaluation/__init__.py` | 91 |
| `src/tracegrade/evaluation/aggregate.py` | 4137 |
| `src/tracegrade/evaluation/compare.py` | 4682 |
| `src/tracegrade/evaluation/dataset.py` | 8138 |
| `src/tracegrade/evaluation/engine.py` | 18521 |
| `src/tracegrade/evaluation/execution.py` | 6381 |
| `src/tracegrade/evaluation/export.py` | 7353 |
| `src/tracegrade/evaluation/metrics/__init__.py` | 3259 |
| `src/tracegrade/evaluation/metrics/base.py` | 769 |
| `src/tracegrade/evaluation/metrics/deterministic.py` | 11657 |
| `src/tracegrade/evaluation/metrics/judge.py` | 13853 |
| `src/tracegrade/evaluation/models.py` | 6099 |
| `src/tracegrade/evaluation/storage.py` | 4229 |
| `src/tracegrade/evaluation/tracing.py` | 8069 |
| `src/tracegrade/logging_utils.py` | 3902 |
| `src/tracegrade/providers/__init__.py` | 607 |
| `src/tracegrade/providers/judge_adapter.py` | 3254 |
| `src/tracegrade/providers/offline.py` | 13481 |
| `src/tracegrade/providers/registry.py` | 8668 |
| `src/tracegrade/refund/__init__.py` | 80 |
| `src/tracegrade/refund/agent.py` | 1670 |
| `src/tracegrade/refund/policy.py` | 4657 |
| `src/tracegrade/refund/prompts.py` | 2349 |
| `src/tracegrade/refund/records.py` | 3269 |
| `src/tracegrade/refund/schemas.py` | 1026 |
| `src/tracegrade/refund/tools.py` | 9068 |
| `src/tracegrade/resources/__init__.py` | 44 |
| `src/tracegrade/resources/datasets/__init__.py` | 42 |
| `src/tracegrade/resources/datasets/refund_support_v1.json` | 13120 |
| `src/tracegrade/ui/__init__.py` | 56 |
| `src/tracegrade/ui/app.py` | 2022 |
| `src/tracegrade/ui/components.py` | 13198 |
| `src/tracegrade/ui/pages/compare.py` | 3971 |
| `src/tracegrade/ui/pages/datasets.py` | 5934 |
| `src/tracegrade/ui/pages/evaluate.py` | 12894 |
| `src/tracegrade/ui/pages/home.py` | 3503 |
| `src/tracegrade/ui/pages/playground.py` | 6226 |
| `src/tracegrade/ui/pages/results.py` | 5031 |
| `src/tracegrade/ui/pages/settings_help.py` | 7359 |
| `src/tracegrade/ui/state.py` | 2995 |
| `tests/__init__.py` | 0 |
| `tests/conftest.py` | 4811 |
| `tests/fakes.py` | 2540 |
| `tests/integration/__init__.py` | 0 |
| `tests/integration/test_cli.py` | 4174 |
| `tests/integration/test_engine.py` | 9748 |
| `tests/live/__init__.py` | 0 |
| `tests/live/test_live_providers.py` | 2910 |
| `tests/ui/__init__.py` | 0 |
| `tests/ui/test_app.py` | 5047 |
| `tests/unit/__init__.py` | 0 |
| `tests/unit/test_config_providers.py` | 7867 |
| `tests/unit/test_dataset.py` | 5010 |
| `tests/unit/test_deterministic_metrics.py` | 6054 |
| `tests/unit/test_judge_metrics.py` | 7069 |
| `tests/unit/test_offline_model.py` | 3354 |
| `tests/unit/test_records_policy.py` | 3758 |
| `tests/unit/test_results_storage_export.py` | 7328 |
| `tests/unit/test_tools.py` | 4235 |
| `uv.lock` | 431243 |

## Inventory after the 2026-10-24 redesign (excluding .venv, runs, caches)

| File | Bytes |
|---|---:|
| `.env.example` | 2257 |
| `.gitignore` | 479 |
| `.python-version` | 5 |
| `.streamlit/config.toml` | 269 |
| `README.md` | 15014 |
| `docs/PRODUCT_REQUIREMENTS.md` | 9671 |
| `docs/TESTING_STRATEGY.md` | 5791 |
| `docs/VERIFICATION_REPORT.md` | 7832 |
| `docs/project_book/PROJECT_BOOK.docx` | 1289751 |
| `docs/project_book/PROJECT_BOOK.html` | 813038 |
| `docs/project_book/PROJECT_BOOK.md` | 266301 |
| `docs/project_book/PROJECT_BOOK.pdf` | 4379249 |
| `docs/project_book/build_book.py` | 24881 |
| `docs/project_book/chapters/00_front_matter.md` | 2120 |
| `docs/project_book/chapters/01_part1_identity.md` | 7355 |
| `docs/project_book/chapters/02_part2_domain.md` | 5452 |
| `docs/project_book/chapters/03_part3_architecture.md` | 9013 |
| `docs/project_book/chapters/04_part4_source.md` | 20513 |
| `docs/project_book/chapters/05_part5_methodology.md` | 13924 |
| `docs/project_book/chapters/06_part6_ui.md` | 9461 |
| `docs/project_book/chapters/07_part7_build.md` | 7018 |
| `docs/project_book/chapters/08_part8_to_10.md` | 11961 |
| `docs/project_book/chapters/11_part11_evolution.md` | 5325 |
| `docs/project_book/chapters/12_part12_reference.md` | 22486 |
| `docs/project_book/chapters/13_appendices.md` | 10675 |
| `docs/project_book/images/01_overview.jpg` | 36422 |
| `docs/project_book/images/02_new_evaluation.jpg` | 24362 |
| `docs/project_book/images/03_results_summary.jpg` | 38612 |
| `docs/project_book/images/04_results_charts.jpg` | 32612 |
| `docs/project_book/images/05_results_cases.jpg` | 37269 |
| `docs/project_book/images/06_case_detail.jpg` | 42478 |
| `docs/project_book/images/07_compare.jpg` | 36758 |
| `docs/project_book/images/08_compare_cases.jpg` | 37907 |
| `docs/project_book/images/09_playground.jpg` | 29713 |
| `docs/project_book/images/10_datasets.jpg` | 49000 |
| `docs/project_book/images/11_settings.jpg` | 37270 |
| `docs/project_book/images/diagrams/diagram_076668d00152.png` | 27211 |
| `docs/project_book/images/diagrams/diagram_076668d00152.svg` | 14009 |
| `docs/project_book/images/diagrams/diagram_2684b4427118.png` | 155070 |
| `docs/project_book/images/diagrams/diagram_2684b4427118.svg` | 26683 |
| `docs/project_book/images/diagrams/diagram_69e2247bb2b8.png` | 196740 |
| `docs/project_book/images/diagrams/diagram_69e2247bb2b8.svg` | 31747 |
| `docs/project_book/images/diagrams/diagram_719cbfb7f617.png` | 72203 |
| `docs/project_book/images/diagrams/diagram_719cbfb7f617.svg` | 22473 |
| `docs/project_book/images/diagrams/diagram_a714b5fe33b2.png` | 81593 |
| `docs/project_book/images/diagrams/diagram_a714b5fe33b2.svg` | 32549 |
| `docs/project_book/images/diagrams/diagram_ac1540b4a95c.png` | 170660 |
| `docs/project_book/images/diagrams/diagram_ac1540b4a95c.svg` | 30964 |
| `docs/project_book/images/diagrams/diagram_e04f0809e107.png` | 221718 |
| `docs/project_book/images/diagrams/diagram_e04f0809e107.svg` | 34683 |
| `pyproject.toml` | 2357 |
| `requirements-dev.txt` | 2050 |
| `requirements.txt` | 7165 |
| `src/tracegrade/__init__.py` | 22 |
| `src/tracegrade/__main__.py` | 58 |
| `src/tracegrade/cli.py` | 21520 |
| `src/tracegrade/config.py` | 6842 |
| `src/tracegrade/errors.py` | 1384 |
| `src/tracegrade/evaluation/__init__.py` | 91 |
| `src/tracegrade/evaluation/aggregate.py` | 4137 |
| `src/tracegrade/evaluation/compare.py` | 5006 |
| `src/tracegrade/evaluation/dataset.py` | 8138 |
| `src/tracegrade/evaluation/engine.py` | 19093 |
| `src/tracegrade/evaluation/execution.py` | 6639 |
| `src/tracegrade/evaluation/export.py` | 7353 |
| `src/tracegrade/evaluation/metrics/__init__.py` | 3259 |
| `src/tracegrade/evaluation/metrics/base.py` | 769 |
| `src/tracegrade/evaluation/metrics/deterministic.py` | 11657 |
| `src/tracegrade/evaluation/metrics/judge.py` | 14147 |
| `src/tracegrade/evaluation/models.py` | 6318 |
| `src/tracegrade/evaluation/storage.py` | 4229 |
| `src/tracegrade/evaluation/tracing.py` | 8064 |
| `src/tracegrade/logging_utils.py` | 3902 |
| `src/tracegrade/providers/__init__.py` | 607 |
| `src/tracegrade/providers/judge_adapter.py` | 3776 |
| `src/tracegrade/providers/offline.py` | 13754 |
| `src/tracegrade/providers/registry.py` | 9438 |
| `src/tracegrade/refund/__init__.py` | 80 |
| `src/tracegrade/refund/agent.py` | 3960 |
| `src/tracegrade/refund/policy.py` | 4657 |
| `src/tracegrade/refund/prompts.py` | 2446 |
| `src/tracegrade/refund/records.py` | 3297 |
| `src/tracegrade/refund/schemas.py` | 1350 |
| `src/tracegrade/refund/tools.py` | 9588 |
| `src/tracegrade/resources/__init__.py` | 44 |
| `src/tracegrade/resources/datasets/__init__.py` | 42 |
| `src/tracegrade/resources/datasets/refund_support_v1.json` | 12911 |
| `src/tracegrade/ui/__init__.py` | 56 |
| `src/tracegrade/ui/app.py` | 2022 |
| `src/tracegrade/ui/components.py` | 13205 |
| `src/tracegrade/ui/pages/compare.py` | 3971 |
| `src/tracegrade/ui/pages/datasets.py` | 6101 |
| `src/tracegrade/ui/pages/evaluate.py` | 12894 |
| `src/tracegrade/ui/pages/home.py` | 3503 |
| `src/tracegrade/ui/pages/playground.py` | 6372 |
| `src/tracegrade/ui/pages/results.py` | 5031 |
| `src/tracegrade/ui/pages/settings_help.py` | 7199 |
| `src/tracegrade/ui/state.py` | 2995 |
| `start.py` | 6514 |
| `tests/__init__.py` | 0 |
| `tests/conftest.py` | 4813 |
| `tests/fakes.py` | 2540 |
| `tests/integration/__init__.py` | 0 |
| `tests/integration/test_cli.py` | 4174 |
| `tests/integration/test_engine.py` | 9751 |
| `tests/live/__init__.py` | 0 |
| `tests/live/test_live_providers.py` | 3189 |
| `tests/ui/__init__.py` | 0 |
| `tests/ui/test_app.py` | 5060 |
| `tests/unit/__init__.py` | 0 |
| `tests/unit/test_config_providers.py` | 7891 |
| `tests/unit/test_dataset.py` | 5014 |
| `tests/unit/test_deterministic_metrics.py` | 6138 |
| `tests/unit/test_judge_metrics.py` | 7358 |
| `tests/unit/test_offline_model.py` | 4406 |
| `tests/unit/test_records_policy.py` | 3884 |
| `tests/unit/test_results_storage_export.py` | 7606 |
| `tests/unit/test_tools.py` | 4351 |
| `uv.lock` | 431243 |

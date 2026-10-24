# Progress record

Durable status file for the TraceGrade work. A new session should read this file and
`MASTER_ENGINEERING_LOG.md` before continuing.

## Layout of the workspace (`AI Agent Evaluation/`)

| Path | Role |
|---|---|
| `tracegrade/` | **The product.** Self-contained repository; contains only TraceGrade's own material. |
| `TraceGrade_Engineering_Records/` | These records (logs, decisions, known issues, discovery report, handover). Delivered separately from the product. |
| `.claude/launch.json` | Local preview configuration used during UI verification (not part of the product). |

The extracted copies of the originally supplied ZIP (`_original_extract/`, `_baseline_env/`)
were deleted on 2026-10-24 at the user's request; the ZIP in the user's Downloads folder was
not touched.

## Phase status

| Phase | Status |
|---|---|
| Product definition, core, UI, hardening | Done |
| Offline verification (tests, static analysis, clean installs) | Done — 158 tests pass |
| Live verification on Groq | Done — agent 16/16 correct refunds; judge metrics scored without errors |
| Redesign to remove all traces of the reference project | Done |
| Single launcher `start.py` | Done, verified |
| Project book (MD/HTML/PDF/DOCX) | Done, rebuilt after the redesign |
| Engineering records moved out of the repository | Done |

## Last successful verification

`tracegrade/docs/VERIFICATION_REPORT.md` (2026-10-24). The pre-redesign offline report is kept
here as `VERIFICATION_REPORT_offline_2026-10-23.md`.

## Known open items

* OpenAI provider not verified live (no key).
* The default Groq judge `openai/gpt-oss-120b` was not used for a full run on the verification
  day because its 200k tokens/day quota had been exhausted by diagnostics.
* No licence chosen for the product.

## Next concrete actions (if resuming)

1. With an OpenAI key: `uv run tracegrade evaluate --agent-provider openai --judge-provider openai`
   and record the result in the verification report.
2. Repeat a Groq judge run on another day with the default judge.
3. Rebuild the book after any doc change: `uv run --group docs python docs/project_book/build_book.py`.

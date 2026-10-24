# Final handover — TraceGrade 1.0.0

## What it is

An evaluation workbench for tool-using LangChain agents. It runs the bundled refund-desk agent
over 16 synthetic scenarios, records answers, tool calls, refund tickets and execution traces,
and scores each run with 7 credential-free metrics and 6 DeepEval LLM-judge metrics. Runs are
stored, inspectable, comparable, resumable and exportable. CLI + Streamlit UI.

## Run it

```bash
cd tracegrade
python start.py
```

`start.py` creates `.env` if missing, installs the locked dependencies (uv if installed,
otherwise pip into `.venv`), checks the configuration and opens the web app. Your Groq key is
already in `tracegrade/.env` (git-ignored) with Groq selected for agent and judge.

## Test

```bash
uv run pytest                     # 158 offline tests
TRACEGRADE_RUN_LIVE_TESTS=1 uv run pytest tests/live -m live -v    # real API calls
```

## Where things are

| Need | Location |
|---|---|
| Architecture, code walkthrough, methodology | `tracegrade/docs/project_book/PROJECT_BOOK.pdf` (.md/.docx/.html) |
| What was verified and how | `tracegrade/docs/VERIFICATION_REPORT.md` |
| Requirements | `tracegrade/docs/PRODUCT_REQUIREMENTS.md` |
| History, decisions, known issues | this folder |

## Open items for the owner

1. Verify OpenAI live if you plan to use it.
2. Choose a licence.
3. Rotate the Groq key if this conversation transcript is shared (the key was pasted in chat).
4. Consider moving the project out of OneDrive (slow `.venv` sync).

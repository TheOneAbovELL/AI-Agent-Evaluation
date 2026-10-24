# Part III — Requirements and system architecture

## 10. Requirements

The authoritative list is `docs/PRODUCT_REQUIREMENTS.md`: 21 functional requirements (FR-1 …
FR-21), 8 non-functional requirements (NFR-1 … NFR-8) and 10 acceptance criteria (AC-1 …
AC-10). Chapter 87 maps each one to its implementation and evidence. In short:

* **Functional:** the refund agent and its policy (FR-1–4); datasets and reproducible dates
  (FR-5–6); execution capture (FR-7); deterministic and DeepEval metrics with thresholds and
  statuses (FR-8–10); aggregation, persistence, export, comparison and resume (FR-11–15);
  providers and preflight validation (FR-16–17); CLI, UI and interactive chat (FR-18–20); the
  bundled dataset (FR-21).
* **Non-functional:** works offline (NFR-1), reproducible (NFR-2), reliable (NFR-3), honest
  reporting (NFR-4), secure (NFR-5), maintainable (NFR-6), testable (NFR-7), predictable
  resource use (NFR-8).

## 11. Architecture overview

TraceGrade is one Python package with four layers and two front ends:

```mermaid
flowchart TB
    subgraph FE[Front ends]
        CLI[cli.py]
        UI[ui/ Streamlit app + pages]
    end
    subgraph EV[evaluation/]
        ENG[engine.py<br/>orchestration]
        EXE[execution.py<br/>run agent once]
        TRC[tracing.py<br/>TraceRecorder]
        MET[metrics/<br/>deterministic + judge]
        AGG[aggregate.py]
        STO[storage.py<br/>RunStore]
        EXP[export.py / compare.py]
        DS[dataset.py]
        MOD[models.py<br/>result schema]
    end
    subgraph SUT[refund/ — system under test]
        AG[agent.py]
        TL[tools.py + ledger]
        PO[policy.py]
        RC[records.py]
        PR[prompts.py / schemas.py]
    end
    subgraph PV[providers/]
        REG[registry.py]
        OFF[offline.py]
        JAD[judge_adapter.py]
    end
    subgraph BASE[foundation]
        CFG[config.py]
        ERR[errors.py]
        LOG[logging_utils.py]
    end
    CLI --> ENG
    UI --> ENG
    UI --> STO
    CLI --> STO
    ENG --> EXE --> AG
    EXE --> TRC
    ENG --> MET
    ENG --> AGG
    ENG --> STO
    ENG --> DS
    AG --> TL --> PO --> RC
    AG --> PR
    ENG --> REG
    REG --> OFF
    REG --> JAD
    MET --> JAD
    EV --> BASE
    SUT --> BASE
    PV --> BASE
```

**Responsibilities.** The *foundation* provides settings, the exception hierarchy and
logging. *refund/* is the system under test and knows nothing about evaluation. *providers/*
turns a serialisable `ModelSpec` into a chat model or a DeepEval judge. *evaluation/* loads
datasets, runs the agent per case, scores, aggregates, stores and exports. The *front ends*
only translate user input into a `RunRequest` and render `RunRecord`s.

## 12. Module dependency rules

```mermaid
flowchart LR
    ui --> evaluation
    cli --> evaluation
    evaluation --> refund
    evaluation --> providers
    providers --> refund
    refund --> config
    providers --> config
    evaluation --> config
```

* `refund` never imports `evaluation` or `providers`; the agent chooses its structured-output
  strategy from the chat-model class name.
* `providers.offline` imports `refund.policy`/`records`/`schemas` (to apply the same rules).
  There are no import cycles: every module is imported during the test run (the UI pages
  through Streamlit's AppTest, `__main__` through a subprocess test) without error.
* No module performs I/O or network calls at import time.

## 13. Data flow

```mermaid
flowchart TB
    J[(dataset JSON)] -->|parse + validate| L[LoadedDataset<br/>+ sha256]
    L --> R[RunRequest]
    S[(.env / environment)] --> C[Settings] --> R
    R -->|preflight| P{errors?}
    P -- yes --> X[stop: nothing executed]
    P -- no --> RR[RunRecord status=running]
    RR --> CASE[per case]
    CASE --> CTX[RefundToolContext<br/>records, reference date, ledger]
    CTX --> AGT[agent graph]
    AGT --> EXE[AgentExecution]
    EXE --> DM[deterministic metrics]
    EXE --> TC[LLMTestCase + _trace_dict] --> JM[DeepEval metrics]
    DM --> CR[CaseResult]
    JM --> CR
    CR --> RR
    RR -->|after every case| F[(runs/run_id.json)]
    F --> E[exports: JSON, CSV, Markdown]
    F --> CMP[compare]
```

## 14. Component interactions — an evaluation run

```mermaid
sequenceDiagram
    participant U as CLI / UI
    participant E as EvaluationEngine
    participant R as provider registry
    participant X as execute_case
    participant G as agent graph
    participant T as tools + ledger
    participant M as metrics
    participant S as RunStore
    U->>E: preflight(request)
    E->>R: build agent model / judge (no network)
    E-->>U: errors, warnings, info
    U->>E: run(request, on_event, should_cancel)
    E->>S: save(record: running)
    par up to max_concurrency cases
        E->>R: build_chat_model(spec)
        E->>X: execute_case(case, dataset, model)
        X->>G: ainvoke(user message, TraceRecorder)
        G->>T: tool calls
        T-->>G: JSON results (ledger updated)
        G-->>X: messages + structured AgentReply
        X-->>E: AgentExecution
        E->>M: deterministic metrics (sync)
        E->>M: judge metrics (async, bounded, retried)
        E->>S: save(record + case)
        E-->>U: event case_finished
    end
    E->>S: save(record: completed / interrupted)
    E-->>U: event run_finished
```

## 15. Sequence — one judge metric

```mermaid
sequenceDiagram
    participant E as engine
    participant J as run_judge_metric
    participant D as DeepEval metric
    participant L as judge model
    E->>J: definition, case, execution, factory
    J->>J: check_applicable (else SKIPPED)
    J->>J: build LLMTestCase, attach trace
    loop attempt <= max_retries + 1
        J->>D: fresh instance, a_measure() with timeout
        D->>L: one or more judge prompts
        alt success
            D-->>J: score, reason
            J->>J: validate 0 <= score <= 1 (else ERROR)
            J-->>E: PASSED / FAILED
        else transient error (timeout, 429, 5xx, connection)
            J->>J: backoff 2^n + jitter, retry
        else permanent error
            J-->>E: ERROR (redacted message)
        end
    end
```

## 16. Sequence — a playground turn

```mermaid
sequenceDiagram
    participant B as Browser
    participant P as playground page
    participant A as agent (InMemorySaver)
    B->>P: chat_input("I'm C1002 ...")
    P->>A: invoke(message, thread_id)
    A->>A: tool calls (history, date, calculate, ticket)
    A-->>P: messages + structured AgentReply
    P->>P: new tool calls = calls[seen:]
    P-->>B: rerun: render turns, tool calls, tickets
```

## 17. Run state transitions

```mermaid
stateDiagram-v2
    [*] --> running: run() after successful preflight
    running --> completed: all cases finished
    running --> interrupted: should_cancel() / Ctrl+C / UI stop / cancellation
    running --> failed: unexpected exception in the engine
    interrupted --> running: resume(run_id) (dataset hash must match)
    completed --> running: resume --retry-errors (re-runs agent-error cases)
    completed --> [*]
    failed --> [*]
```

A case has its own status: `error` (agent did not complete), `failed` (≥1 metric failed),
`incomplete` (no failure, ≥1 metric error, or nothing evaluated) or `passed`.

## 18. Design decisions and trade-offs

The most consequential design decisions, with the main alternative considered:

| Decision | Chosen | Main alternative | Why |
|---|---|---|---|
| Ground truth for outcomes | Tool ledger + `refund_outcome` | Judge the reply text | Exact, free, independent of wording |
| Policy | Deterministic module + oracle test | Prompt only | One source of truth for guardrails, offline model and dataset checks |
| "Today" | Dataset reference date | Machine clock | Reproducibility |
| Trace capture | Own `TraceRecorder` | DeepEval `CallbackHandler` | DeepEval clears traces after use; avoid global state and cloud path |
| DeepEval usage | Call `a_measure` per metric | `deepeval.evaluate()` | Per-metric timeout/retry/error handling, own result model |
| Credential-free mode | Rule-based offline model | None / canned outputs | Exercise the real graph, tools and metrics |
| Storage | One JSON file per run | SQLite / server DB | Simple, inspectable, sufficient |
| UI | Streamlit multipage | JS front end | Python-first, as requested |
| Aggregation | Per-metric only | Weighted overall score | Do not mix exact checks with opinions |
| Agent retries | None at run level | Retry whole run | Tool side effects (tickets) |

The main trade-off accepted is a dependency on one private DeepEval attribute
(`LLMTestCase._trace_dict`). It is exercised by tests for all seven DeepEval metric classes,
so an incompatible DeepEval upgrade fails loudly in CI rather than silently.

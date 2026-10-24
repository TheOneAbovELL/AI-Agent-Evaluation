# Appendix A — Agent system prompt and tool contracts

The system prompt and its fingerprint function, included verbatim from
`src/tracegrade/refund/prompts.py`:

{{code:src/tracegrade/refund/prompts.py:python}}

**Tool outputs.** Every tool returns a JSON string. The following outputs were captured from a
real offline run (run `20261024-060919-c6a98a`, case `mixed-eligibility`, policy mode
`enforced`):

```text
// get_purchase_history {"customer_id": "C1002"}
{"status": "found", "customer_id": "c1002", "purchases": {"webcam": {"price": 59.0, "date": "2026-08-30"}, "usb_hub": {"price": 25.0, "date": "2026-11-05"}}}

// get_current_date {}
{"today": "2026-11-20"}

// calculate_refund {"customer_id": "C1002", "items": [{"name": "usb_hub"}]}
{"status": "ok", "amount": 25.0, "eligible_items": [{"item": "usb_hub", "price": 25.0}], "ineligible_items": []}

// issue_refund_ticket {"customer_id": "C1002", "amount": 25.0}
{"status": "issued", "ticket_id": "TKT-0001", "customer_id": "c1002", "amount": 25.0, "message": "Refund ticket issued; the amount should arrive in the customer's bank account soon."}
```

Other documented outputs (from the tool implementation and unit tests):
`{"status": "not_found", "message": "No customer account was found for customer ID 'C9999'."}`;
`{"status": "rejected", "reason": "amount 33.0 exceeds the remaining eligible amount 23.0"}`;
in `prompt_only` mode `calculate_refund` sums the prices of all purchased requested items
regardless of dates and lists unknown items, e.g. `{"status": "ok", "amount": 113.0,
"unknown_items": ["hat"]}`.

# Appendix B — The bundled dataset

Included verbatim from `src/tracegrade/resources/datasets/refund_support_v1.json`. All
customers, purchases and amounts are synthetic.

{{code:src/tracegrade/resources/datasets/refund_support_v1.json:json}}

# Appendix C — Core algorithm listings

## C.1 Refund policy (`src/tracegrade/refund/policy.py`)

{{code:src/tracegrade/refund/policy.py:python}}

## C.2 Deterministic metrics (`src/tracegrade/evaluation/metrics/deterministic.py`)

{{code:src/tracegrade/evaluation/metrics/deterministic.py:python}}

## C.3 Aggregation (`src/tracegrade/evaluation/aggregate.py`)

{{code:src/tracegrade/evaluation/aggregate.py:python}}

## C.4 Tools, ledger and guardrails (`src/tracegrade/refund/tools.py`)

{{code:src/tracegrade/refund/tools.py:python}}

## C.5 Trace recorder (`src/tracegrade/evaluation/tracing.py`)

{{code:src/tracegrade/evaluation/tracing.py:python}}

## C.6 Case execution (`src/tracegrade/evaluation/execution.py`)

{{code:src/tracegrade/evaluation/execution.py:python}}

## C.7 DeepEval metrics and the judge runner (`src/tracegrade/evaluation/metrics/judge.py`)

{{code:src/tracegrade/evaluation/metrics/judge.py:python}}

## C.8 Evaluation engine (`src/tracegrade/evaluation/engine.py`)

{{code:src/tracegrade/evaluation/engine.py:python}}

## C.9 Offline reference model (`src/tracegrade/providers/offline.py`)

{{code:src/tracegrade/providers/offline.py:python}}

# Appendix D — A worked example from a real run

Captured on 2026-10-24 with the offline reference model:

```text
$ uv run tracegrade evaluate --agent-provider offline --judge-provider none --cases mixed-eligibility,quote-without-ticket,missing-customer-id --label "appendix example"
Run 20261024-060919-c6a98a: 3 case(s), agent offline:reference, judge none
  [1/3] quote-without-ticket             passed
  [2/3] missing-customer-id              passed
  [3/3] mixed-eligibility                passed

Run 20261024-060919-c6a98a - completed
Agent: offline rule-based reference model (not an LLM).
Cases: 3/3 finished | passed 3 | failed 0 | incomplete 0 | agent errors 0 | case pass rate 100.0%
metric                     kind           thr   mean   pass rate  passed  err  skip
-------------------------  -------------  ----  -----  ---------  ------  ---  ----
refund_outcome             deterministic  1.00  1.000  100.0%     3/3     0    0
expected_tool_coverage     deterministic  1.00  1.000  100.0%     2/2     0    1
forbidden_tool_avoidance   deterministic  1.00  1.000  100.0%     2/2     0    1
tool_argument_match        deterministic  1.00  1.000  100.0%     2/2     0    1
tool_order                 deterministic  1.00  1.000  100.0%     2/2     0    1
answer_action_consistency  heuristic      1.00  1.000  100.0%     3/3     0    0
task_completion            llm_judge      0.80  n/a    n/a        0/0     0    3
step_efficiency            llm_judge      0.80  n/a    n/a        0/0     0    3
plan_quality               llm_judge      0.80  n/a    n/a        0/0     0    3
plan_adherence             llm_judge      0.80  n/a    n/a        0/0     0    3
argument_correctness       llm_judge      0.90  n/a    n/a        0/0     0    3
deepeval_tool_correctness  deterministic  0.90  1.000  100.0%     2/2     0    1
answer_correctness         llm_judge      0.80  n/a    n/a        0/0     0    3
```

The cases finished out of order (they run concurrently); the stored record keeps dataset
order. `missing-customer-id` is skipped by the tool metrics because it expects no tools, and
the judge metrics are skipped on every case because no judge was configured — both are shown
as *skipped*, never as passes.

**Case result excerpt** (`mixed-eligibility`; tool outputs shortened, the full outputs are in
Appendix A):

```json
{
  "case_id": "mixed-eligibility",
  "status": "passed",
  "execution": {
    "status": "completed",
    "answer": "A refund ticket (TKT-0001) for $25.00 has been issued for usb_hub. It should arrive in your bank account soon. Not refunded: webcam: it was purchased 82 days ago, outside the 30-day refund window.",
    "conversation_continues": false,
    "tool_calls": [
      {"name": "get_purchase_history", "args": {"customer_id": "C1002"}, "output": "{...}", "call_id": "offline_call_2"},
      {"name": "get_current_date", "args": {}, "output": "{\"today\": \"2026-11-20\"}", "call_id": "offline_call_4"},
      {"name": "calculate_refund", "args": {"customer_id": "C1002", "items": [{"name": "usb_hub"}]}, "output": "{...}", "call_id": "offline_call_6"},
      {"name": "issue_refund_ticket", "args": {"customer_id": "C1002", "amount": 25.0}, "output": "{...}", "call_id": "offline_call_8"}
    ],
    "tickets": [{"ticket_id": "TKT-0001", "customer_id": "c1002", "amount": 25.0}],
    "latency_ms": 85.1
  },
  "metrics": [
    {"metric_id": "refund_outcome", "status": "passed", "score": 1.0, "threshold": 1.0, "reason": "Refund of $25.00 issued, as expected."},
    {"metric_id": "expected_tool_coverage", "status": "passed", "score": 1.0, "threshold": 1.0, "reason": "4/4 expected tool calls made."},
    {"metric_id": "forbidden_tool_avoidance", "status": "skipped", "score": null, "threshold": 1.0, "reason": "case lists no forbidden tools"},
    {"metric_id": "tool_argument_match", "status": "passed", "score": 1.0, "threshold": 1.0, "reason": "4/4 expected calls had matching arguments."},
    {"metric_id": "tool_order", "status": "passed", "score": 1.0, "threshold": 1.0, "reason": "Longest in-order match covers 4/4 expected steps (...)."},
    {"metric_id": "answer_action_consistency", "status": "passed", "score": 1.0, "threshold": 1.0, "reason": "Answer reports the issued refund amount $25.00."},
    {"metric_id": "task_completion", "status": "skipped", "score": null, "threshold": 0.8, "reason": "No judge model configured for this run."}
  ]
}
```

**Trace excerpt** — the beginning of the span tree the judge metrics would receive (system
prompt shortened; the full text is in Appendix A):

```json
{
  "name": "refund_agent",
  "type": "agent",
  "input": "C1002 here. Please refund the webcam and the USB hub.",
  "output": "A refund ticket (TKT-0001) for $25.00 has been issued for usb_hub. ...",
  "available_tools": ["get_purchase_history", "get_current_date", "calculate_refund", "issue_refund_ticket"],
  "children": [
    {
      "name": "model_call_1", "type": "llm", "model": "tracegrade-offline",
      "input": [
        {"role": "system", "content": "Role: refund desk assistant for an online electronics and accessories shop. ..."},
        {"role": "human", "content": "C1002 here. Please refund the webcam and the USB hub."}
      ],
      "start_ms": 14.9,
      "output": {
        "content": "Plan: identify customer C1002, then check the requested items against the purchase history and the refund policy.",
        "tool_calls": [{"name": "get_purchase_history", "args": {"customer_id": "C1002"}}]
      },
      "duration_ms": 2.2
    },
    {"name": "get_purchase_history", "type": "tool", "input": {"customer_id": "C1002"}, "start_ms": 21.2, "output": "{\"status\": \"found\", ...}", "duration_ms": 0.4},
    {
      "name": "model_call_2", "type": "llm", "model": "tracegrade-offline",
      "input": [
        {"role": "ai", "content": "Plan: identify customer C1002, ...", "tool_calls": [{"name": "get_purchase_history", "args": {"customer_id": "C1002"}}]},
        {"role": "tool", "content": "{\"status\": \"found\", ...}", "tool_name": "get_purchase_history"}
      ],
      "start_ms": 24.4,
      "output": {"content": "Checking today's date to apply the 30-day refund window.", "tool_calls": [{"name": "get_current_date", "args": {}}]},
      "duration_ms": 1.1
    },
    {"name": "get_current_date", "type": "tool", "input": {}, "start_ms": 27.3, "output": "{\"today\": \"2026-11-20\"}", "duration_ms": 0.2}
  ]
}
```

The trace continues with `model_call_3` → `calculate_refund`, `model_call_4` →
`issue_refund_ticket` and `model_call_5`, whose output is the `reply` response-tool call
(excluded from "tools called"). Each LLM span lists only the messages that are new since the
previous call.

**Markdown export excerpt** (`tracegrade runs export 20261024-060919-c6a98a --format md`):

```markdown
# Evaluation run 20261024-060919-c6a98a

- Status: **completed**
- Created: 2026-10-24T00:39:19.238294+00:00
- Dataset: `refund_support_v1` (bundled:refund_support_v1, sha256 `7650740fad2c`)
- Reference date: 2026-11-20
- Agent: `offline:reference` (offline rule-based reference model, not an LLM)
- Judge: none (LLM-judge metrics skipped)
- Policy mode: enforced
- Prompt fingerprint: `dc554b7e11a46a64`
```

# Appendix E — Product requirements

{{doc:docs/PRODUCT_REQUIREMENTS.md}}

# Appendix F — Testing strategy

{{doc:docs/TESTING_STRATEGY.md}}

# Appendix G — Verification report

{{doc:docs/VERIFICATION_REPORT.md}}

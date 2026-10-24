"""Datasets: browse cases and purchase records, understand the schema, validate uploads."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from tracegrade.errors import TraceGradeError
from tracegrade.evaluation.dataset import parse_dataset
from tracegrade.refund.policy import assess_refund
from tracegrade.ui import state

cfg = state.settings()
st.title("Datasets")
st.caption(
    "A dataset is one JSON file holding the customers' purchase records, the reference date "
    "used as “today”, and the evaluation cases. The bundled dataset is synthetic sample data."
)

options = state.dataset_options()
label = st.selectbox("Dataset", list(options))
try:
    loaded = state.load_dataset(options[label])
except TraceGradeError as exc:
    st.error(str(exc))
    st.stop()
ds = loaded.dataset

cols = st.columns(4)
cols[0].metric("Cases", len(ds.cases))
cols[1].metric("Customers", len(ds.customers))
cols[2].metric("Reference date", ds.reference_date.isoformat())
cols[3].metric("Refund window", f"{ds.refund_window_days} days")
if ds.description:
    st.markdown(ds.description)
for warning in ds.warnings():
    st.warning(warning)

tab_cases, tab_customers, tab_schema, tab_validate = st.tabs(
    ["Cases", "Purchase records", "Schema", "Validate a file"]
)

with tab_cases:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Case": c.id,
                    "Customer message": c.input,
                    "Expected refund": c.expected_refund_total,
                    "Expected tools": " → ".join(t.name for t in c.expected_tools),
                    "Forbidden tools": ", ".join(c.forbidden_tools),
                    "Tags": ", ".join(c.tags),
                }
                for c in ds.cases
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={"Expected refund": st.column_config.NumberColumn(format="$%.2f")},
    )
    case_id = st.selectbox("Inspect case", [c.id for c in ds.cases])
    case = ds.case(case_id)
    st.json(case.model_dump(exclude_none=True), expanded=2)
    if case.customer and case.requested_items is not None:
        assessment = assess_refund(
            ds.records(),
            case.customer,
            case.requested_items,
            ds.reference_date,
            ds.refund_window_days,
        )
        st.markdown("**What the policy code decides for this request**")
        if not assessment.customer_found:
            st.caption(f"Customer `{case.customer}` does not exist → no refund.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Item": d.item,
                            "Decision": d.status.value,
                            "Price": float(d.price) if d.price else None,
                            "Reason": d.reason,
                        }
                        for d in assessment.items
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            st.caption(f"Refundable total: ${assessment.refundable_total:.2f}")

with tab_customers:
    rows = [
        {
            "Customer": cid,
            "Item": item,
            "Price": float(p.price),
            "Purchase date": p.date.isoformat(),
            "Age (days)": (ds.reference_date - p.date).days,
        }
        for cid, items in ds.customers.items()
        for item, p in items.items()
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={"Price": st.column_config.NumberColumn(format="$%.2f")},
    )
    st.caption(
        "Age is relative to the dataset's reference date. Negative age = future-dated purchase."
    )

with tab_schema:
    st.markdown(
        """
| Field | Required | Meaning |
|---|---|---|
| `schema_version` | no (1) | Format version. |
| `name`, `description` | name | Identifies the dataset in runs. |
| `reference_date` | yes | The date the agent's `get_current_date` tool returns. |
| `refund_window_days` | no (30) | Policy window used by guardrails and the oracle. |
| `customers` | yes | `{customer_id: {item: {price, date}}}`. |
| `cases[].id` | yes | Unique, lowercase letters/digits/`-`/`_`. |
| `cases[].input` | yes | The customer message. |
| `cases[].expected_output` | no | Reference answer for the answer-correctness judge. |
| `cases[].expected_tools` | no | `[{name, input_parameters?}]` in expected order. |
| `cases[].forbidden_tools` | no | Tool names that must not be called. |
| `cases[].expected_refund_total` | no | `0` = no ticket; `>0` = exact refund; omitted = not checked. |
| `cases[].customer`, `requested_items` | no | Lets tests recompute the expected refund from the policy. |
| `cases[].tags`, `notes` | no | Free-form. |
"""
    )
    st.download_button(
        "Download this dataset as a template",
        data=json.dumps(json.loads(loaded.model_dump_json())["dataset"], indent=2),
        file_name=f"{ds.name}.json",
        mime="application/json",
        icon=":material/download:",
    )

with tab_validate:
    st.caption(
        "Validation only; nothing is saved. Upload on the New evaluation page to use a file."
    )
    file = st.file_uploader("JSON dataset", type=["json"], key="validate_upload")
    if file is not None:
        try:
            checked = parse_dataset(
                file.getvalue(), source=file.name, max_bytes=cfg.max_upload_bytes
            )
        except TraceGradeError as exc:
            st.error(str(exc))
        else:
            st.success(
                f"Valid: '{checked.dataset.name}' with {len(checked.dataset.cases)} cases "
                f"(sha256 {checked.sha256[:12]})."
            )
            for warning in checked.dataset.warnings():
                st.warning(warning)

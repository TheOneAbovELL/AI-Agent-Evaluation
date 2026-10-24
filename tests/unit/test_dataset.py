from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracegrade.errors import DatasetError
from tracegrade.evaluation.dataset import (
    LoadedDataset,
    bundled_dataset_names,
    load_dataset,
    parse_dataset,
    resolve_dataset,
)
from tracegrade.refund.policy import assess_refund


def minimal(**case_overrides: object) -> dict:
    case = {"id": "c1", "input": "hello", "expected_refund_total": 0}
    case.update(case_overrides)
    return {
        "name": "mini",
        "reference_date": "2026-10-15",
        "customers": {"u": {"desk_mat": {"price": 1, "date": "2026-10-01"}}},
        "cases": [case],
    }


def raw(payload: object) -> bytes:
    return json.dumps(payload).encode()


def test_bundled_dataset_is_valid(bundled: LoadedDataset) -> None:
    ds = bundled.dataset
    assert "refund_support_v1" in bundled_dataset_names()
    assert len(ds.cases) == 16 and ds.warnings() == []
    assert len(bundled.sha256) == 64


def test_bundled_expected_refunds_match_policy_oracle(bundled: LoadedDataset) -> None:
    """Every expected_refund_total must follow from the purchase data and the policy code."""
    ds = bundled.dataset
    checked = 0
    for case in ds.cases:
        if case.customer is None or case.requested_items is None:
            continue
        assessment = assess_refund(
            ds.records(),
            case.customer,
            case.requested_items,
            ds.reference_date,
            ds.refund_window_days,
        )
        expects_ticket = case.expected_refund_total and case.expected_refund_total > 0
        if expects_ticket:
            assert float(assessment.refundable_total) == case.expected_refund_total, case.id
            calc = next(t for t in case.expected_tools if t.name == "calculate_refund")
            eligible = sorted(d.item for d in assessment.eligible_items)
            assert sorted(i["name"] for i in calc.input_parameters["items"]) == eligible, case.id
        elif "quote" not in case.tags:
            assert assessment.refundable_total == 0, case.id
        checked += 1
    assert checked >= 12


def test_valid_minimal_dataset() -> None:
    loaded = parse_dataset(raw(minimal()), source="mem")
    assert loaded.dataset.case("c1").input == "hello"
    assert loaded.dataset.warnings() == [
        "case 'c1': no expected_output, answer-correctness is skipped"
    ]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"{not json", "not valid JSON"),
        (b"[1, 2]", "must be a JSON object"),
        (b"\xff\xfe\x00", "not UTF-8"),
        (raw({**minimal(), "cases": []}), "cases"),
        (raw(minimal(id="Bad ID!")), "case id"),
        (raw(minimal(expected_refund_total=-1)), "expected_refund_total"),
        (raw(minimal(unknown_field=1)), "unknown_field"),
        (
            raw(minimal(expected_tools=[{"name": "t"}], forbidden_tools=["t"])),
            "both expected and forbidden",
        ),
        (raw({**minimal(), "reference_date": "15/10/2026"}), "reference_date"),
    ],
)
def test_invalid_datasets_are_rejected_with_reason(content: bytes, message: str) -> None:
    with pytest.raises(DatasetError, match=message):
        parse_dataset(content, source="mem")


def test_duplicate_case_ids_rejected() -> None:
    payload = minimal()
    payload["cases"].append(dict(payload["cases"][0]))
    with pytest.raises(DatasetError, match="duplicate case ids"):
        parse_dataset(raw(payload), source="mem")


def test_duplicate_item_names_rejected() -> None:
    payload = minimal()
    payload["customers"]["u"]["Desk_mat"] = {"price": 2, "date": "2026-10-01"}
    with pytest.raises(DatasetError, match="duplicate item"):
        parse_dataset(raw(payload), source="mem")


def test_size_limit() -> None:
    with pytest.raises(DatasetError, match="limit"):
        parse_dataset(raw(minimal()), source="mem", max_bytes=10)


def test_unknown_tool_names_are_warnings() -> None:
    loaded = parse_dataset(raw(minimal(expected_tools=[{"name": "teleport"}])), source="mem")
    assert any("teleport" in w for w in loaded.dataset.warnings())


def test_file_loading_and_resolution(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_bytes(raw(minimal()))
    assert load_dataset(path).source == str(path)
    assert resolve_dataset(str(path)).dataset.name == "mini"
    assert resolve_dataset("bundled:refund_support_v1").source == "bundled:refund_support_v1"
    assert resolve_dataset("refund_support_v1").dataset.name == "refund_support_v1"
    with pytest.raises(DatasetError, match="not found"):
        load_dataset(tmp_path / "missing.json")
    with pytest.raises(DatasetError, match="No bundled dataset"):
        resolve_dataset("bundled:nope")


def test_select_unknown_case() -> None:
    ds = parse_dataset(raw(minimal()), source="mem").dataset
    assert [c.id for c in ds.select(None)] == ["c1"]
    with pytest.raises(DatasetError, match="no case 'zzz'"):
        ds.select(["zzz"])

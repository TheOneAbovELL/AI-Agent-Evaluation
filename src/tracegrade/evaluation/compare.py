"""Comparison of two runs (baseline vs. candidate).

Runs are only strictly comparable when they used the same dataset content, reference
date, thresholds and judge. ``compare_runs`` reports every difference in that set as a
compatibility warning rather than refusing, because comparing e.g. two agent models on
the same dataset is the main use case.
"""

from __future__ import annotations

from pydantic import BaseModel

from tracegrade.evaluation.models import RunRecord


class MetricDelta(BaseModel):
    metric_id: str
    name: str
    baseline_mean: float | None
    candidate_mean: float | None
    mean_delta: float | None
    baseline_pass_rate: float | None
    candidate_pass_rate: float | None
    pass_rate_delta: float | None


class CaseChange(BaseModel):
    case_id: str
    baseline_status: str | None
    candidate_status: str | None
    changed_metrics: list[str]


class RunComparison(BaseModel):
    baseline_id: str
    candidate_id: str
    warnings: list[str]
    metrics: list[MetricDelta]
    cases: list[CaseChange]

    @property
    def regressions(self) -> list[CaseChange]:
        return [
            c
            for c in self.cases
            if c.baseline_status == "passed" and c.candidate_status != "passed"
        ]

    @property
    def improvements(self) -> list[CaseChange]:
        return [
            c
            for c in self.cases
            if c.baseline_status != "passed" and c.candidate_status == "passed"
        ]


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else round(b - a, 4)


def compatibility_warnings(a: RunRecord, b: RunRecord) -> list[str]:
    out = []
    if a.config.dataset_sha256 != b.config.dataset_sha256:
        out.append("Different dataset content (sha256 differs).")
    if a.config.reference_date != b.config.reference_date:
        out.append("Different reference dates.")
    shared = set(a.config.thresholds) & set(b.config.thresholds)
    differing = sorted(m for m in shared if a.config.thresholds[m] != b.config.thresholds[m])
    if differing:
        out.append(
            f"Different thresholds for {', '.join(differing)}; their pass rates are not "
            "directly comparable."
        )
    ja = a.config.judge.label if a.config.judge else None
    jb = b.config.judge.label if b.config.judge else None
    if ja != jb:
        out.append(f"Different judges ({ja} vs {jb}); judge scores are not directly comparable.")
    if a.config.policy_mode != b.config.policy_mode:
        out.append("Different policy modes (enforced vs prompt_only).")
    if a.config.prompt_fingerprint != b.config.prompt_fingerprint:
        out.append("Different agent system prompts.")
    if a.status.value != "completed" or b.status.value != "completed":
        out.append("At least one run did not complete.")
    return out


def compare_runs(baseline: RunRecord, candidate: RunRecord) -> RunComparison:
    a_metrics = {m.metric_id: m for m in baseline.summary.metrics}
    b_metrics = {m.metric_id: m for m in candidate.summary.metrics}
    metric_ids = [m for m in a_metrics if m in b_metrics]
    warnings = compatibility_warnings(baseline, candidate)
    only = sorted(set(a_metrics) ^ set(b_metrics))
    if only:
        warnings.append(f"Metrics present in only one run (not compared): {', '.join(only)}.")
    deltas = [
        MetricDelta(
            metric_id=mid,
            name=a_metrics[mid].name,
            baseline_mean=a_metrics[mid].mean_score,
            candidate_mean=b_metrics[mid].mean_score,
            mean_delta=_delta(a_metrics[mid].mean_score, b_metrics[mid].mean_score),
            baseline_pass_rate=a_metrics[mid].pass_rate,
            candidate_pass_rate=b_metrics[mid].pass_rate,
            pass_rate_delta=_delta(a_metrics[mid].pass_rate, b_metrics[mid].pass_rate),
        )
        for mid in metric_ids
    ]
    a_cases = {c.case_id: c for c in baseline.cases}
    b_cases = {c.case_id: c for c in candidate.cases}
    changes = []
    for cid in list(dict.fromkeys([*a_cases, *b_cases])):
        ca, cb = a_cases.get(cid), b_cases.get(cid)
        changed = []
        if ca and cb:
            for mid in metric_ids:
                ma, mb = ca.metric(mid), cb.metric(mid)
                if ma and mb and ma.status != mb.status:
                    changed.append(f"{mid}: {ma.status.value} -> {mb.status.value}")
        changes.append(
            CaseChange(
                case_id=cid,
                baseline_status=ca.status.value if ca else None,
                candidate_status=cb.status.value if cb else None,
                changed_metrics=changed,
            )
        )
    return RunComparison(
        baseline_id=baseline.run_id,
        candidate_id=candidate.run_id,
        warnings=warnings,
        metrics=deltas,
        cases=changes,
    )

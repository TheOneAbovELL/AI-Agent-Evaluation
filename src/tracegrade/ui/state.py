"""Shared UI state: settings, run store and dataset discovery.

The UI only offers datasets that are bundled with the package or stored in the
configured datasets directory. It never accepts a free-form filesystem path, so a browser
user cannot make the server read arbitrary files.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import streamlit as st

from tracegrade.config import Settings, get_settings
from tracegrade.errors import TraceGradeError
from tracegrade.evaluation.dataset import (
    LoadedDataset,
    bundled_dataset_names,
    parse_dataset,
    resolve_dataset,
)
from tracegrade.evaluation.models import RunRecord
from tracegrade.evaluation.storage import RunStore

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")

RESULTS_PAGE = "pages/results.py"
EVALUATE_PAGE = "pages/evaluate.py"
SETTINGS_PAGE = "pages/settings_help.py"


def settings() -> Settings:
    try:
        return get_settings()
    except TraceGradeError as exc:
        st.error(f"Configuration error\n\n{exc}")
        if exc.hint:
            st.caption(exc.hint)
        st.stop()
        raise  # unreachable; keeps type checkers happy


def store() -> RunStore:
    return RunStore(settings().runs_dir)


def list_runs() -> list[RunRecord]:
    try:
        return store().list_runs()
    except TraceGradeError as exc:
        st.error(str(exc))
        return []


def dataset_options() -> dict[str, str]:
    """Display label -> dataset spec understood by ``resolve_dataset``."""
    options = {f"{name} (bundled)": f"bundled:{name}" for name in bundled_dataset_names()}
    folder = settings().datasets_dir
    if folder.exists():
        for path in sorted(folder.glob("*.json")):
            options[f"{path.name} (datasets folder)"] = str(path)
    return options


@st.cache_data(show_spinner=False, max_entries=32)
def _load_cached(spec: str, mtime: float, max_bytes: int) -> LoadedDataset:
    return resolve_dataset(spec, max_bytes)


def load_dataset(spec: str) -> LoadedDataset:
    mtime = Path(spec).stat().st_mtime if not spec.startswith("bundled:") else 0.0
    return _load_cached(spec, mtime, settings().max_upload_bytes)


def save_uploaded_dataset(filename: str, raw: bytes) -> tuple[Path, LoadedDataset]:
    """Validate an upload and store it in the datasets folder under a safe name."""
    cfg = settings()
    parse_dataset(raw, source=f"upload:{filename}", max_bytes=cfg.max_upload_bytes)  # validate
    stem = _SAFE_NAME.sub("_", Path(filename).stem).strip("._") or "dataset"
    folder = cfg.datasets_dir
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{stem}.json"
    if target.exists() and target.read_bytes() != raw:
        target = folder / f"{stem}-{hashlib.sha256(raw).hexdigest()[:8]}.json"
    target.write_bytes(raw)
    return target, parse_dataset(raw, source=str(target), max_bytes=cfg.max_upload_bytes)

"""File-based run store.

Each run is one JSON file, ``<runs_dir>/<run_id>.json``. Files are written atomically
(write to a temporary file in the same directory, then ``os.replace``), and the engine
rewrites the file after every finished case, so an interrupted run keeps all completed
cases and can be resumed.

A plain directory of JSON files was chosen over a database: runs are small (tens to
hundreds of KB), written by one process at a time, human-readable, easy to back up,
diff and delete, and need no server.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from pydantic import ValidationError

from tracegrade.errors import RunNotFoundError, StorageError
from tracegrade.evaluation.models import RunRecord
from tracegrade.logging_utils import get_logger

log = get_logger("evaluation.storage")

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")


def validate_run_id(run_id: str) -> str:
    """Reject anything that is not a plain id (prevents path traversal)."""
    if not _RUN_ID.match(run_id):
        raise RunNotFoundError(f"Invalid run id: {run_id!r}")
    return run_id


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, run_id: str) -> Path:
        return self.root / f"{validate_run_id(run_id)}.json"

    def save(self, record: RunRecord) -> Path:
        path = self._path(record.run_id)
        payload = record.model_dump_json(indent=2)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{record.run_id}.", suffix=".tmp", dir=self.root
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                # On Windows a concurrent reader can briefly block replace; retry a little.
                for attempt in range(5):
                    try:
                        os.replace(tmp_name, path)
                        break
                    except PermissionError:
                        if attempt == 4:
                            raise
                        time.sleep(0.1 * (attempt + 1))
            finally:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)
        except OSError as exc:
            raise StorageError(f"Could not save run {record.run_id} to {path}: {exc}") from exc
        return path

    def load(self, run_id: str) -> RunRecord:
        path = self._path(run_id)
        if not path.exists():
            raise RunNotFoundError(f"No run '{run_id}' in {self.root}.")
        try:
            return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, json.JSONDecodeError) as exc:
            raise StorageError(
                f"Run file {path} is corrupt or from an unsupported version: {exc}"
            ) from exc

    def exists(self, run_id: str) -> bool:
        try:
            return self._path(run_id).exists()
        except RunNotFoundError:
            return False

    def list_runs(self) -> list[RunRecord]:
        """All readable runs, newest first. Unreadable files are logged and skipped."""
        if not self.root.exists():
            return []
        runs: list[RunRecord] = []
        for path in self.root.glob("*.json"):
            if not _RUN_ID.match(path.stem):
                continue
            try:
                runs.append(RunRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValidationError, json.JSONDecodeError) as exc:
                log.warning(
                    "skipping unreadable run file",
                    extra={"ctx": {"path": str(path), "error": type(exc).__name__}},
                )
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs

    def delete(self, run_id: str) -> None:
        path = self._path(run_id)
        if not path.exists():
            raise RunNotFoundError(f"No run '{run_id}' in {self.root}.")
        path.unlink()

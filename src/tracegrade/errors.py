"""Exception hierarchy.

Every error that TraceGrade raises on purpose derives from ``TraceGradeError`` so that
the CLI and the UI can show a readable message instead of a stack trace, while unexpected
exceptions still surface as genuine bugs.
"""

from __future__ import annotations


class TraceGradeError(Exception):
    """Base class for expected, user-facing errors."""

    #: Short hint shown next to the message (CLI and UI).
    hint: str | None = None

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        if hint is not None:
            self.hint = hint


class ConfigurationError(TraceGradeError):
    """Invalid or incomplete configuration (bad provider name, missing API key, ...)."""

    hint = "Check your .env file or the Settings page. See `tracegrade doctor`."


class DatasetError(TraceGradeError):
    """A dataset file could not be read or failed validation."""

    hint = "Validate the file with `tracegrade dataset validate <path>`."


class ProviderUnavailableError(ConfigurationError):
    """A provider is known but cannot be used (package missing or credential absent)."""


class RunNotFoundError(TraceGradeError):
    """A requested run id does not exist in the run store."""


class StorageError(TraceGradeError):
    """Run persistence failed (permissions, disk full, corrupt file)."""

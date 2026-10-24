"""Structured logging with secret redaction.

Log records may carry structured context via ``extra={"ctx": {...}}``. The text formatter
renders it as ``key=value`` pairs, the JSON formatter as fields. A redaction filter masks
anything that looks like a provider API key, plus the literal values of configured keys.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

LOGGER_NAME = "tracegrade"

# OpenAI (sk-...), Groq (gsk_...), Anthropic (sk-ant-...), generic bearer tokens.
_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gsk_[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
]
_REDACTED = "***REDACTED***"


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Mask API-key-like substrings and the given literal secret values."""
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, _REDACTED)
    for pattern in _KEY_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact(message, self._secrets)
        record.args = None
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            record.ctx = {k: redact(str(v), self._secrets) for k, v in ctx.items()}
        return True


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{datetime.fromtimestamp(record.created, UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        )
        ctx = getattr(record, "ctx", None)
        if ctx:
            base += " | " + " ".join(f"{k}={v}" for k, v in ctx.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            payload.update(ctx)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(
    level: str = "INFO",
    fmt: str = "text",
    log_file: Path | None = None,
    secrets: Iterable[str] = (),
) -> logging.Logger:
    """Configure the ``tracegrade`` logger. Safe to call repeatedly (idempotent)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    formatter: logging.Formatter = JsonFormatter() if fmt == "json" else TextFormatter()
    redactor = RedactingFilter(secrets)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(redactor)
    logger.addHandler(stream)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")

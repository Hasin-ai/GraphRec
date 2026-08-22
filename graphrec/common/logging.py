"""Structured logging.

Every line carries the `request_id` that the response returns as `X-Request-Id`
and that a failure echoes as `error.reference`, so a tenant quoting a reference
leads directly to the log lines for that request.

NR-NF-06 bans secrets, raw event payloads, passwords, tokens and foreign tenant
identifiers from log lines. `_Redactor` is a backstop for that, not a licence to
log carelessly: the primary defence is not passing such values in the first
place.
"""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

from pythonjsonlogger import jsonlogger

#: Bound by the request middleware, and by the worker for the job it is running,
#: so a line emitted deep in domain code is attributable without threading a
#: logger argument through every call.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
actor_id_var: ContextVar[str | None] = ContextVar("actor_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)


#: Keys whose values never appear in a log line, whatever they contain.
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "secret",
        "api_key",
        "credential_secret",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "pepper",
        "private_key",
        "payload",
        "products",
        "events",
        "impressions",
        "context",
    }
)

#: Value-shaped secrets that can appear inside an otherwise innocuous string.
_SENSITIVE_PATTERNS = (
    re.compile(r"gr_live_[A-Za-z0-9_\-]+"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9._\-]{10,}"),  # a JWT
)

_REDACTED = "[redacted]"


#: Attributes the logging module itself puts on every record. Rewriting these
#: corrupts the record: `args` in particular must keep its exact type, because
#: `LogRecord.getMessage` does `msg % args`, and a tuple silently turned into a
#: list makes every %-formatted third-party line raise.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def _redact(value: Any, _depth: int = 0) -> Any:
    if _depth > 6:
        return _REDACTED
    if isinstance(value, dict):
        return {
            key: (_REDACTED if key.lower() in _SENSITIVE_KEYS else _redact(inner, _depth + 1))
            for key, inner in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_redact(item, _depth + 1) for item in value)
    if isinstance(value, list):
        return [_redact(item, _depth + 1) for item in value]
    if isinstance(value, str):
        for pattern in _SENSITIVE_PATTERNS:
            value = pattern.sub(_REDACTED, value)
        return value
    return value


class ContextFilter(logging.Filter):
    """Attach the ambient correlation identifiers and redact the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.tenant_id = tenant_id_var.get()
        record.actor_id = actor_id_var.get()
        record.job_id = job_id_var.get()

        # Only `extra=` fields are redacted. Reserved attributes are left alone:
        # they are the logging module's own, and rewriting them corrupts the
        # record rather than protecting anything.
        for key, value in list(record.__dict__.items()):
            if key.startswith("_") or key in _RESERVED_RECORD_ATTRS:
                continue
            if key.lower() in _SENSITIVE_KEYS:
                record.__dict__[key] = _REDACTED
            elif isinstance(value, dict | list | tuple | str):
                record.__dict__[key] = _redact(value)
        return True


class _Formatter(jsonlogger.JsonFormatter):
    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record.setdefault("timestamp", self.formatTime(record, self.datefmt))
        log_record.pop("taskName", None)
        for key in ("request_id", "tenant_id", "actor_id", "job_id"):
            if log_record.get(key) is None:
                log_record.pop(key, None)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())

    if fmt == "json":
        # python-json-logger 2.x leaves `JsonFormatter.__init__` unannotated,
        # so strict mypy sees an untyped call. The arguments are `logging`'s own
        # and are checked by the format string at runtime.
        handler.setFormatter(
            _Formatter(  # type: ignore[no-untyped-call]
                "%(timestamp)s %(level)s %(logger)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn installs its own handlers; route them through ours so every line
    # is one format and carries the correlation context.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

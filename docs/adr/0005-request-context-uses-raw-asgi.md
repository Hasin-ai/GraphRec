# ADR 0005 — Request context is raw ASGI middleware, and logging redacts by allow-list

**Status:** Accepted
**Phase:** 1
**Date:** 2026-08-22

## Context

Every response must carry `X-Request-Id`, and every failure must echo the same
value as `error.reference`, so that a tenant quoting a reference out of an error
banner leads an operator to that request's log lines. Domain code deep in the
stack must be able to log without having a logger threaded through every call, so
the identifier lives in a `ContextVar`.

Starlette's `BaseHTTPMiddleware` runs the downstream handler in a separate task.
The `ContextVar` binding does not survive that, so the identifier is lost exactly
where it is needed.

## Decision

`RequestContextMiddleware` is written against the raw ASGI interface. It binds the
`ContextVar` in the same task the handler runs in, wraps `send` to stamp the
header on `http.response.start`, and resets the binding in a `finally`.

The identifier is bound outermost, ahead of the body-limit middleware, so even a
request rejected for size carries a quotable reference.

A client-supplied `X-Request-Id` is echoed, for callers correlating across
services, but truncated to 64 characters: it is a trace aid, never a trusted log
key.

## Consequences and one bug this design surfaced

`ContextFilter` redacts `extra=` fields as a backstop for NR-NF-06. The first
implementation skipped reserved attributes by testing
`key in logging.LogRecord.__dict__` — which is the *class* dictionary, holding
methods, not the instance attributes of a record.

The result: `record.args` was passed through the redactor and returned as a list.
`LogRecord.getMessage` does `msg % args`, and `%` treats a tuple as an argument
list but a list as a single value. Every `%`-formatted log line from any
third-party library — httpx, uvicorn, SQLAlchemy — raised `TypeError: not enough
arguments for format string`.

The fix names the reserved attributes explicitly in `_RESERVED_RECORD_ATTRS`, and
`_redact` preserves tuples as tuples.

The lesson is recorded because it generalises: a redactor sits on the path of
every log line in the system, including the ones emitted while handling a failure.
It must be conservative about what it rewrites, and it must never change a type.

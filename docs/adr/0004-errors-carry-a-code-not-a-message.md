# ADR 0004 — Errors carry a code; the sentence comes from a line-cited catalogue

**Status:** Accepted
**Phase:** 1
**Date:** 2026-08-22

## Context

BUILD_PROMPT §9 designates roughly sixty user-facing strings in the console
prototype as approved product copy, to be *reproduced, not paraphrased*. The
console pre-validates against the same rules the server enforces, so any
divergence means the two surfaces tell a tenant different things about the same
failure — and the tenant is left deciding which one is lying.

The error envelope publishes three field names to tenants on the console's
`/integration` page: `class`, `reason` and `reference`. Those names cannot change.
`code` and `field_errors` are additive.

## Decision

`GraphRecError` carries **no message of its own**. It carries a `code`, and
`reason` is resolved from `graphrec/common/error_copy.py` at render time.

The catalogue is hand-written rather than generated, because the prototype
concatenates around its own values (`'Plan ' + pl.id + ' is closed...'`) and a
parser would produce fragments rather than sentences. Each entry instead cites the
`dc.html` line it came from, and `tests/contract/test_error_copy_parity.py`
asserts — for 33 verbatim entries and 7 templated ones — that the string still
appears at the cited line, curly quotation marks included.

Templated entries interpolate from settings rather than hard-coding a number, so
changing `TRAINING_GLOBAL_CONCURRENCY` changes the sentence instead of leaving it
stating a stale figure. They are verified by checking the template's fixed literal
segments against the prototype line, since the rendered sentence never appears
there literally.

A missing code raises `MissingErrorCopy`, which is fatal by design. There is no
generic fallback: an unreviewed sentence must never reach a tenant.

## Consequences

- Adding an error means adding approved copy. That is a deliberate speed bump.
- `NotFoundError` takes no arguments and names no resource type. The 404 copy is
  asserted against a list of nouns it must never contain, because "that exists but
  isn't yours" is itself a disclosure (gate 4).
- The unhandled-exception handler never relays the exception message (NR-NF-06),
  and the framework's 422 translator drops Pydantic's `input` field, which would
  otherwise echo a rejected password or raw event payload straight back.
- `reason` is a sentence for a human. Clients branch on `code` and `class`. Only
  the latter two are stable contracts.

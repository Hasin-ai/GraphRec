# ADR 0001 — Body limits are per-endpoint, not global (D7)

**Status:** Proposed. Built to, pending confirmation.
**Phase:** 1
**Date:** 2026-08-22

## Context

The inherited configuration carried a single `MAX_REQUEST_BODY_BYTES = 16384`
applied to every request.

The console offers a catalogue synchronisation bounded at 5,000 products
(dc.html L1612) and an event batch bounded at 5,000 events (L1627). A 5,000-item
product payload with identifiers, titles, categories and prices does not fit in
16 KB by roughly two orders of magnitude. A single global ceiling is therefore
either 37× too small for the bulk routes, or — if raised to accommodate them —
it hands every ordinary endpoint, including unauthenticated sign-in, a 2 MB
budget it has no use for.

That second option is the one that matters. The body limit is the only bound
that applies *before* authentication, so it is the only thing standing between an
anonymous caller and memory allocation.

## Decision

Two named settings, and a per-path choice between them:

- `max_request_body_bytes = 16_384` — every route by default.
- `max_bulk_body_bytes = 2_097_152` — routes that accept a bounded collection,
  listed explicitly in `BULK_PATH_SUFFIXES`.

Enforcement streams the body and counts as it arrives, rather than trusting
`Content-Length`, so a chunked request cannot declare 1 KB and send 100 MB.
`Content-Length` is still checked first, because rejecting before reading is
cheaper when the header is honest.

A rejection is `413` with `error.class = "validation"`, which the console already
has a designed destination for ("Paste more than 5,000 products, or the word
OVERSIZE", L1358).

`Settings` validates that the bulk limit exceeds the default, so a configuration
that silently inverts them fails at startup rather than in production.

## Consequences

- The bulk route list is a maintenance obligation. A new collection endpoint that
  nobody adds to `BULK_PATH_SUFFIXES` will reject legitimate traffic at 16 KB.
  This is the safe direction to fail in, and it fails loudly and immediately.
- Matching is by path suffix because the paths carry no tenant segment (NR-NF-02),
  so a suffix is unambiguous.
- Both bounds are named settings, per the constraint that every user-facing bound
  must be configurable rather than a literal in the code.

## Alternatives rejected

- **One global limit raised to 2 MB.** Gives every unauthenticated endpoint a 2 MB
  pre-auth allocation budget for no benefit.
- **Reverse-proxy enforcement only.** Correct as defence in depth, but it puts the
  bound outside the application, where it cannot produce the approved error copy
  and is not covered by the test suite.

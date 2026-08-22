# ADR 0013 — Offset paging for the console, cursors for volume reads

**Status:** Accepted — confirmed by instruction to proceed (D10)
**Phase:** 5
**Gate:** BUILD_PROMPT marks Phase 5 🛑 *"CONFIRM D10 (pagination)"*.

## Context

BUILD_PROMPT offers `limit`/`offset`, opaque cursors, or both, and recommends
both. The instruction to complete Phases 4–8 was given without a separate answer
to the gate.

The console decides half of it on its own. Every table it draws carries a count
of the form "8 of 12" — `count: list.length + ' of ' + s.products.length`
(dc.html L1316), and the same construction on submissions, jobs, versions and
users. **A cursor cannot produce the second number.** A keyset scan knows
whether there is another page; it does not know how many rows are behind it
without a second query that is exactly the `COUNT(*)` a cursor was adopted to
avoid.

The other half is decided by the reads that are not a console. Exporting an
interaction history, streaming a submission's errors, or walking a catalogue for
a training snapshot are deep scans over tables that grow to millions of rows.
`OFFSET 900000` makes PostgreSQL read and discard nine hundred thousand rows per
page, and a row inserted during the walk shifts every subsequent page by one, so
a consumer both skips and repeats records without any error.

## Decision

**Console list endpoints take `limit` and `offset` and return a `total`.**
`GET /v1/products` is the first: `{products, total, limit, offset}`. `limit`
defaults to 50 and is bounded at 200; `offset` is bounded below at 0. The total
is computed with the *same* predicate list as the page — built once in
`_conditions` — because two hand-written `WHERE` clauses is how a list comes to
say "8 of 12" while showing nine.

Ordering is `updated_at DESC, external_product_id`. The tie-breaker is not
decoration: two products written in the same transaction share a timestamp to
the microsecond, and without a second key PostgreSQL may order them differently
between the count and the page, or between page 1 and page 2.

**Volume reads take an opaque cursor** and return no total. Phase 6's submission
errors and Phase 7's usage ledger are the first of these. None exists yet, so no
cursor implementation is built in this phase — building the encoder before the
first caller means guessing at what it must encode.

## Consequences

* Deep offsets on a console list are slow, and the 200-row `limit` bound does
  not prevent `offset=100000`. Acceptable: a catalogue screen with a filter bar
  is not how anyone walks 250,000 products, and the endpoint that *is* comes
  with a cursor.
* `total` costs a second query per list request. It is a `COUNT(*)` over the
  tenant's own rows behind an RLS predicate the index already supports, and the
  console renders it unconditionally, so making it optional would save nothing
  and add a branch.
* Two paging vocabularies exist in one API. They are distinguished by which
  endpoint you are calling, not by a parameter, so no caller has to choose.

## Alternatives

**Cursor everywhere.** Correct under concurrent writes and unable to render the
console's own count. It would mean either changing the prototype or adding a
`GET /count` beside every list, which is the same query with worse ergonomics.

**Offset everywhere.** Fine until the first tenant exports a year of events, at
which point it is a production incident rather than a design flaw to revisit.

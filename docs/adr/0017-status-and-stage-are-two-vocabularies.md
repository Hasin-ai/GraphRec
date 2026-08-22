# ADR 0017 — A submission has a status *and* a stage, and they are different vocabularies

**Status:** Accepted
**Phase:** 6
**Gate:** none.

## Context

The prototype draws two different things on the submission detail page and they
do not have the same values. There is a badge — the coarse answer to "did this
work?" — and there is a four-position rail: **received → validating → applying →
completed** (L1382-L1389). A single field cannot serve both: the rail's
`validating` is not a verdict, and the badge's `succeeded` is not a position.

Collapsing them would force one of two bad renderings. Either the badge shows
`applying`, which asks the tenant to know that applying is a kind of
in-progress, or the rail shows `processing`, which is not one of its four
positions and cannot be drawn.

## Decision

Two fields on the wire, with a derivation between them rather than two stored
values:

* **`stage`** — the rail position, from the database's own vocabulary
  (`received` | `validating` | `applying` | `completed`, plus `failed`). This is
  what `submissions.status` stores and what the control transaction advances.
* **`status`** — the badge, derived: `processing` | `succeeded` | `failed`.

The column keeps the *stage* vocabulary because the stage is what the processor
actually knows at each point; the badge is a function of it and of
`failed_count`. Storing both would let them disagree, and there is no reading of
a disagreement that helps anyone.

Two further vocabularies in the same response are also kept apart deliberately:

* **Counts are a partition, not a tally:** `received = accepted + updated +
  skipped + failed`. A tenant can add them up and get the number they sent,
  which is the only property that makes the numbers checkable.
* **`failed_count` is exact; `error_count` is the number of samples kept**,
  capped at 100. A submission with 4,000 failures reports `failed_count: 4000`
  and `error_count: 100`. Reporting the cap as the failure count would understate
  a broken export by a factor of forty.

## Consequences

* `GET /v1/submissions/{id}` is one endpoint for both kinds of submission, as
  BUILD_PROMPT requires, because both kinds share both vocabularies.
* A console can render the badge without knowing the rail, and the rail without
  interpreting the badge.
* Adding a rail position is a migration; adding a badge value is not. The
  derivation is the seam.

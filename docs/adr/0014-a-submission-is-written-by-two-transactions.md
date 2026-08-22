# ADR 0014 — A submission is written by two transactions, and only one of them may count

**Status:** Accepted
**Phase:** 6
**Gate:** none. BUILD_PROMPT marks no 🛑 on ingestion.

## Context

BUILD_PROMPT asks Phase 6 for *"streaming, bounded-memory validation, staging
then a single merge transaction"*. Phase 4 had already settled that the job
worker runs each handler inside exactly one transaction
(`graphrec/jobs/worker.py::_run_handler`): the handler's writes and
`queue.succeed()` commit together, so a handler that fails leaves nothing behind
and the job is retried from a clean slate. That property is why the queue can
be at-least-once without being at-least-once *visibly*.

Those two requirements agree about the merge and disagree about everything else
the tenant can see. A single transaction means the console watching
`GET /v1/submissions/{id}` sees `received` for the whole run and then, in one
step, `completed` — the four-position rail the prototype draws (L1382-L1389) is
a rail with two positions on it. Publishing progress from inside the handler's
transaction is not possible: nothing it writes is visible until it commits.

The obvious repairs are both wrong.

* **Commit per chunk.** The merge stops being one transaction. A crash halfway
  leaves a partially merged catalogue that no retry can reason about, because
  the retry cannot tell which half it is looking at.
* **Report progress out of band** — Redis, a log line, a websocket. Then the
  stage a tenant reads and the counts a tenant reads come from two systems with
  two failure modes, and the interesting case is exactly the one where they
  disagree.

## Decision

Two transactions, with an asymmetry between them that is the whole of the
design:

* **The handler's transaction** carries everything that must be true together —
  the staged items, the merged rows, the per-item error samples, the five
  counts, `completed_at`, and the cleared `raw_payload`. One commit, or none.
* **The control transaction** (`JobContext.control()`, added in Phase 4 for
  exactly this) carries the **stage** and nothing else. It commits immediately,
  so `validating` and `applying` are readable while the handler is still
  running, and it survives the handler failing, so a failed submission can say
  *why* rather than saying `received` forever.

**The control transaction never writes a count.** That is the invariant, and it
is what makes the two transactions unable to contradict each other on anything
a tenant could act on. A stage is a position; a count is a fact about data. If
the handler rolls back, the stage is stale by one step and the counts are
absent — which is exactly what "we were working on it and it did not finish"
should look like. Had the control transaction been allowed to publish
`accepted: 4,000` for a merge that then rolled back, the submission would be
lying about the tenant's own data.

Both control writes are guarded on `completed_at IS NULL`, so a late control
write cannot reopen a submission that has already finished.

Bounded memory comes from the payload never being held in Python. The submitted
collection stays in `submissions.raw_payload` (JSONB) and is read back in
windows of `VALIDATION_CHUNK = 500` with
`jsonb_array_elements(...) WITH ORDINALITY ... OFFSET ... LIMIT`, which also
gives each item a stable ordinal for `submission_errors`. `raw_payload` is
cleared on completion, so a stored payload is a working file rather than a
retained one (NR-NF-06).

## Consequences

* A worker holds two connections for the length of a submission. Pool sizing
  must account for it; the ingest test fixtures use `NullPool` because a pool
  sized for a request path would deadlock waiting for itself.
* `ctx.stage(...)` is called once per chunk, which is also the cancellation
  boundary and the lease renewal. A submission cannot be cancelled mid-chunk,
  which bounds cancellation latency at 500 items rather than at the whole
  batch.
* A crash between the last control write and the handler's commit leaves a
  submission reading `applying` with no counts. The retry re-runs it whole and
  overwrites both. This is visible and correct; it is not silent.

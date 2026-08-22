# ADR 0016 — A repeated collection answers 200, and only a new one answers 202

**Status:** Accepted
**Phase:** 6
**Gate:** none.

## Context

`POST /v1/events/batches` and `POST /v1/products:bulk-upsert` are documented as
`202` + a submission (BUILD_PROMPT L643-645), and both carry a
caller-chosen identifier — `batch_id` and `sync_id` — which makes them
idempotent. An integration that retries a timed-out batch must not enqueue the
batch twice.

So a repeat has to return the *same* submission. The question is what status
line it returns with, and the two are not interchangeable: `202` means "this has
been accepted and work is now queued", which on a retry is false. Work was
queued the first time.

The body cannot carry the difference honestly either. The submission returned by
a repeat is a real submission that may already have completed; a field saying
"this was a repeat" would be describing the request, not the resource, and the
same resource read a second later through `GET /v1/submissions/{id}` would not
have it.

## Decision

* First submission of a `batch_id`/`sync_id` → **`202 Accepted`**, one
  submission, one job.
* Repeat of an identifier already seen for that tenant → **`200 OK`** with the
  existing submission and **no second job**.

The status line is where the difference goes, because the status line is about
the request and the body is about the resource.

The single-event route, `POST /v1/events`, resolves the same question in the
body rather than the status line, and deliberately: it has no submission to
return and the prototype names the outcome directly — `duplicate_confirmed`
alongside `accepted` (L1610). There `200` is correct for both, because both are
a completed operation, and `first_received_at` tells the caller when the event
actually landed.

## Consequences

* An integration can distinguish "I created this" from "this already existed"
  without parsing the body, which is the same property `PUT /v1/products/{id}`
  gives with `201`/`200` (ADR 0012).
* `batch_id` and `sync_id` are separate namespaces (migration 0008), so the
  `/v1/events/batches/{batch_id}` alias cannot be made to answer with a product
  sync by reusing an identifier across kinds.
* Identifiers are per tenant. Two tenants using `batch-001` are two submissions.

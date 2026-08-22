# ADR 0012 — Products take three write verbs, and each one means something

**Status:** Accepted — confirmed by instruction to proceed (D9)
**Phase:** 5
**Gate:** BUILD_PROMPT marks Phase 5 🛑 *"CONFIRM D9 (write model)"*.

## Context

BUILD_PROMPT offers three options for the catalogue's write model and recommends
the third:

* **A.** `POST` only, with a duplicate answering `409`.
* **B.** `PUT` only, idempotent by the external identifier.
* **C.** `POST` **and** `PUT` **and** `PATCH`.

The instruction to complete Phases 4–8 was given without a separate answer to
the gate, so this records the recommended option and names the confirmation for
what it is.

Two facts in the prototype decide it, and they point in opposite directions if
only one verb exists.

The Add product form renders a conflict: *"A product with identifier SKU-4471
already exists. Use a different identifier or update the existing product."*
(dc.html L1604), with `Already exists in this tenant.` beside the input. That
sentence is only true of a create. A `PUT` upsert cannot produce it — it would
have silently replaced the product the tenant was warned about, and the second
half of the message, which tells them what to do next, would describe something
that had already happened.

The integration page, meanwhile, documents `POST /v1/products:bulk-upsert` with
a `sync_id` (L1173), and the Add product page states that the external
identifier "is also the idempotency key for later updates" (L1320). An
integration retrying a timed-out write must not receive a `409` for a product it
successfully created; that turns a network blip into a permanent error requiring
a human.

And the detail page (L1337) renders an Update form pre-filled with five of the
product's fields — not including the description. A `PUT` there would blank the
description on every save, because a replace applies to what the caller omitted
as much as to what they sent.

## Decision

Three verbs, with three distinct meanings:

| Verb | Meaning | Duplicate | Omitted field |
|------|---------|-----------|---------------|
| `POST /v1/products` | Create only | `409 product_already_exists` | Default |
| `PUT /v1/products/{external_id}` | Create or **replace** | Replaces | **Reset to default** |
| `PATCH /v1/products/{external_id}` | Partial update | Updates | **Left alone** |

`PUT` answers `201` the first time and `200` afterwards, so a retrying client
can tell which call created the product without a body field invented for the
purpose.

`PATCH` distinguishes "not mentioned" from "set to null" with a sentinel that is
not `None`, because `{"brand": null}` is a legitimate instruction to clear the
brand. The HTTP layer draws the distinction from Pydantic's `exclude_unset`; the
service carries it as `UNSET`.

There is no `DELETE`. "A disabled product stops being returned by serving
immediately. The record is retained and can be re-enabled by an update."
(L1339–L1340) — so removal is `POST /v1/products/{external_id}:disable`, which
takes a reason and writes it to the audit history, and `products` carries no
`DELETE` grant that would let a handler do otherwise even by mistake.

## Consequences

* Three code paths where option B would have had one. They share `_apply`, and
  the difference between `PUT` and `PATCH` is one call to `_complete` — small
  enough that the divergence risk is a review comment, not an architecture.
* An integration written against `PUT` and a console user working in the same
  catalogue can produce a last-writer-wins overwrite. The prototype anticipates
  this and states the answer at L1335: *"A concurrent change to the same product
  is reported as a state conflict; your entries are kept so you can reconcile
  them."* The copy exists; **the optimistic-concurrency check that would raise
  it does not yet** — there is no version column on `products`. This is recorded
  as an open item in the Phase 5 report rather than quietly deferred.
* `PUT`'s replace semantics are a sharp edge for a hand-written client. It is
  documented on the route and pinned by a test, which is the most that can be
  done for a verb whose meaning is fixed by HTTP.

## Alternatives

**A — `POST` only.** Every integration retry becomes a `409` the caller must
distinguish from a genuine duplicate, which it cannot do without a read.

**B — `PUT` only.** Cheapest, and it discards L1604's conflict entirely. The
prototype is an executable specification; a message it renders is a requirement,
not a nicety.

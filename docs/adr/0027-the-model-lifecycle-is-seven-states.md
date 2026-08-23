# ADR 0027 — A model version has seven states, and the transitions are not symmetric

**Status:** Accepted — confirmed by instruction to proceed
**Phase:** 10
**Date:** 2026-08-23

## Context

D8 asks whether a model version needs seven states or whether some of them are
the same state seen from different angles. The seven are the prototype's, and
`ModelVersionStatus` has carried them since Phase 2: `registered`, `eligible`,
`rejected`, `active`, `retired`, `failed_deployment`, `archived`.

The case for collapsing them is real. `rejected` and `failed_deployment` are
both "this version is not going to serve"; `retired` and `archived` are both
"this version is not serving now". A four-state lifecycle would be simpler to
implement and would render the same five stat cards if the console did the
grouping.

## Decision

**Seven states, and the reason is that four of them differ in what a tenant is
allowed to do next**, which is precisely what a state is for.

* **`registered` → `eligible` | `rejected`.** Registration records the version;
  the metric floor then decides. A version that fails the floor is not a failed
  version — it trained correctly and is not good enough — so `rejected` carries
  a `failure_note` and can be archived, but never activated.
* **`eligible`** is the only state `:activate` accepts. That is the whole
  purpose of separating it from `registered`: a version whose metrics have not
  been judged must not be activatable by a race between registration and
  evaluation.
* **`active`** is bounded by a partial unique index on `tenant_id`, not by
  application code, for the reason Phase 9's concurrency rule is an index.
* **`retired` is not `archived`.** A retired version is the rollback target
  (ER-F-07) and its artifact bytes must still exist; an archived version's
  bytes are deleted. Collapsing them would make "roll back" a request the
  server accepts and then fails to honour, and it would do so only for tenants
  who had archived something — the worst kind of intermittent.
* **`failed_deployment` is not `rejected`.** A version that failed to load is
  a version that may load next time: the bundle may have been the problem, or
  the host, or the disk. `rejected` is a verdict on the model; this is a report
  about an attempt. They are also read differently — the prototype's `v-4`
  panel narrates the failed activation and says the previous version kept
  serving (L704), which is information `rejected` does not carry.
* **`archived` is terminal** and it is the only state that destroys anything.

**The asymmetry is deliberate.** `eligible → active → retired → archived` moves
one way. There is no `archived → retired`, because the bytes are gone and a
state that claims otherwise is a lie the system cannot make true. There is no
`rejected → eligible`, because the floor is a function of metrics that do not
change after registration; a version that should be re-judged is a version that
should be re-trained.

**Archiving keeps the row.** It deletes the artifact and the index; the
`model_versions` row and its `model_evaluation_metrics` survive, so the history
a tenant is comparing against stays queryable after the bytes are gone.

## Consequences

Six transitions to enforce rather than three, and each one needs a refusal with
copy behind it — which the prototype already supplies, and which the `actions`
block on `GET /v1/model-versions/{id}` returns rather than making the console
derive.

The rollback-target protection — a `retired` version immediately preceding the
`active` one cannot be archived (L1749) — is a rule that only exists because
`retired` and `archived` are distinct. It is enforced in the service and pinned
by a test, not by a constraint: "immediately preceding" is a question about
`model_activation_history`, not about a column.

## Related

- ADR 0017 — status and stage are two vocabularies, for the same reason these
  are seven states: a name that covers two situations is a name that has to be
  disambiguated at every read.

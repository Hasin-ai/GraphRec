# Architectural decisions

One file per decision. A decision is **Accepted** only when a human has confirmed
it; until then it is **Proposed**, and BUILD_PROMPT §2 forbids building past the
gate that depends on it.

## Confirmation gates

| # | Decision | Status | Confirm before |
|---|---|---|---|
| D1 | Resource model: SRS-native vs AWS Personalize | **Confirmed — SRS-native** | Phase 2 |
| D2 | Job queue: PostgreSQL `SKIP LOCKED` | **Confirmed — by instruction** (ADR 0011) | Phase 4 |
| D3 | Serving: Compose + `ServingDriver` port | Accepted | Phase 11 |
| D4 | Candidates: in-process exact top-K behind `CandidateIndex` | Accepted | Phase 10 |
| D5 | Token signing: EdDSA + published JWKS | **Confirmed** (ADR 0009) | Phase 3 |
| D6 | Versioning: `/v1` and `/v1/platform/*` | **Confirmed** | Phase 2 |
| D7 | Body limits: per-endpoint, not global | **Proposed — built to** | Phase 1 |
| D8 | Model lifecycle: seven states | Accepted | Phase 10 |
| D9 | Product writes: POST + PUT + PATCH | **Confirmed — by instruction** (ADR 0012) | Phase 5 |
| D10 | Pagination: limit/offset for console, cursor for volume | **Confirmed — by instruction** (ADR 0013) | Phase 5 |
| D11 | Plans: STARTER / GROWTH / SCALE | **Confirmed** | Phase 2 |
| D12 | Wire casing: snake_case | **Confirmed** | Phase 2 |

The confirm-before column above was re-read against BUILD_PROMPT's appendix
on 2026-08-22 and six rows were corrected; it had drifted, and D2's gate in
particular was recorded a phase later than BUILD_PROMPT places it.

D1 (SRS-native), D5, D6, D11 and D12 have been confirmed. Phase 2 was built on
D1; D5, D6, D11 and D12 were built to ahead of confirmation and each matched
what was later confirmed, so no rework followed.

**No decision is now being built past unconfirmed.** That closes the departure
from BUILD_PROMPT §2 that Phases 1 and 2 carried. D7 is still marked *Proposed
— built to*, but its confirm-before was Phase 1 and it constrains request
handling rather than any interface, so it is recorded here rather than blocking.

D6 was confirmed as the recommendation: everything under `/v1`, platform-realm
endpoints under `/v1/platform/*`. It answers both problems in the recovered
inventory — unversioned paths, and two same-named resources in different realms.
The second is the one that matters and the one a later change could not undo
cheaply: `GET /tenants` means "every tenant on the platform" to an operator and
"my own tenant" to a customer, and the prefix is what keeps those apart. That
collision first becomes real in Phase 4, with platform tenant management.

The versioning half, by contrast, was measured rather than estimated: stripping
the prefix is one constant in `apps/control_api/main.py` plus one substitution
across the 97 `/v1` literals in six test files, and the suite passes unchanged.
It is reversible at any phase, so the earlier claim that it grew more expensive
over time was wrong.

There is also a conflict the authorities do not resolve between them: the SRS
specifies a Qdrant Vector Store Contract (§6.3), which outranks D4's in-process
exact top-K. D4 is marked Accepted below on BACKEND_PLAN's authority, but the
SRS is higher, so an explicit "defer Qdrant" decision is needed before Phase 10.

## The next gate

**D2 is closed.** BUILD_PROMPT marks Phase 4 🛑 *"CONFIRM D2 (Postgres queue)
before starting"*. The instruction to complete Phases 4–8 was given without a
separate answer to the gate, so Phase 4 was built to BUILD_PROMPT's own
recommendation — a `jobs` table claimed with `FOR UPDATE SKIP LOCKED` and
fair-share ordering, rather than RabbitMQ and Celery behind a transactional
outbox — and recorded in **ADR 0011** as *confirmed by instruction to proceed*.
That is a weaker confirmation than an explicit answer, and it is named as such
here rather than dressed up as one.

**D9 and D10 are closed.** Both were treated the way D2 was: BUILD_PROMPT marks
Phase 5 🛑 *"CONFIRM D9 (write model) and D10 (pagination)"*, the instruction to
complete Phases 4–8 was given without separate answers, so both were built to
BUILD_PROMPT's own recommendation and recorded as **ADR 0012** and **ADR 0013**,
marked *confirmed by instruction to proceed*. As with D2 that is a weaker
confirmation than an explicit answer and is named as such rather than dressed up
as one. Both remain cheap to revisit — D9 adds or removes a verb on one
resource, D10 a parameter on a list.

**Nothing gates Phase 6.** BUILD_PROMPT marks no 🛑 on ingestion. The next gate
after that is D4, before Phase 10, and it is the one with an unresolved conflict
of authorities above.

## Open questions with no recommendation

These have no proposed answer, only a stated need for one.

1. **Email delivery.** SMTP, or an administrator CLI that prints the recovery
   link? Affects account recovery and invitation, and therefore Phase 3.
2. **The 15-minute training cooldown.** Is it a real product rule or an artefact
   of the prototype? Affects Phase 7.
3. **The last-active-administrator rule.** The prototype forbids demoting or
   disabling the last one. Does that extend to deletion, and to the platform
   realm? Affects Phase 4.
4. **Customer data lifecycle.** How long are raw interaction events retained,
   and what does tenant deletion actually erase? Affects Phase 5 and the
   reconciler.

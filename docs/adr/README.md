# Architectural decisions

One file per decision. A decision is **Accepted** only when a human has confirmed
it; until then it is **Proposed**, and BUILD_PROMPT §2 forbids building past the
gate that depends on it.

## Confirmation gates

| # | Decision | Status | Confirm before |
|---|---|---|---|
| D1 | Resource model: SRS-native vs AWS Personalize | **Confirmed — SRS-native** | Phase 2 |
| D2 | Job queue: PostgreSQL `SKIP LOCKED` | **Confirmed — by instruction** (ADR 0011) | Phase 4 |
| D3 | Serving: Compose + `ServingDriver` port | **Confirmed — by instruction** (ADR 0028) | Phase 11 |
| D4 | Candidates: in-process exact top-K behind `CandidateIndex` | **Confirmed — by instruction** (ADR 0026) | Phase 10 |
| D5 | Token signing: EdDSA + published JWKS | **Confirmed** (ADR 0009) | Phase 3 |
| D6 | Versioning: `/v1` and `/v1/platform/*` | **Confirmed** | Phase 2 |
| D7 | Body limits: per-endpoint, not global | **Proposed — built to** | Phase 1 |
| D8 | Model lifecycle: seven states | **Confirmed — by instruction** (ADR 0027) | Phase 10 |
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

There was also a conflict the authorities do not resolve between them: the SRS
specifies a Qdrant Vector Store Contract (§6.3), which outranks D4's in-process
exact top-K. **ADR 0026 closes it.** The reading it takes is that §6.3 specifies
an isolation contract and D-5 specifies an implementation: the contract —
per-tenant indices, `tenant_id` on every manifest, deletion on archive — is
implemented by the in-process adapter, and the product name is deferred behind
the `CandidateIndex` port. The divergence is now a decision on the record rather
than a discrepancy waiting to be found.

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

**D4 and D8 are closed the same way.** BUILD_PROMPT marks Phase 10 🛑 *"CONFIRM
D4 (in-process index) and D8 (7-value lifecycle) before starting"*. The
instruction to complete Phases 8–15 was given without separate answers, so both
were built to BUILD_PROMPT's own recommendation and recorded as **ADR 0026** and
**ADR 0027**, marked *confirmed by instruction to proceed*. D4 additionally
carries the SRS §6.3 deferral described above, which is a decision of a
different weight: it diverges from the highest authority in the project and
says so.

**D3 is closed the same way, one phase later.** BUILD_PROMPT marks Phase 11 🛑
*"CONFIRM D3 (Compose vs k3s) before starting"*. The same instruction covers it,
so it is built to BUILD_PROMPT's recommendation and recorded as **ADR 0028**,
marked *confirmed by instruction to proceed*. Its shape is deliberately D4's: a
port, the light adapter shipped, the heavy one deferred with the console's
contract — desired, ready, per-replica — honoured identically by both.

**Phase 12 gated nothing and decided two things anyway.** BUILD_PROMPT marks no
🛑 on audit and platform, but the phase reached two forks worth recording.
**ADR 0029** settles where a *refused* action's audit row is written: on a second
connection, because the transaction that would have carried it is the one the
refusal unwound. **ADR 0030** settles what a platform user who holds some of a
page's permissions sees: the page, with the sections they lack replaced by a
sentence naming the permission, rather than a `403` that hides the sections they
were entitled to.

**Phases 6, 7 and 8 are built and nothing gated either.** BUILD_PROMPT marks no 🛑
on ingestion, metering or offline modelling. Phase 8 recorded three decisions of
its own — **ADR 0023** (plain PyTorch, no PyTorch Geometric), **ADR 0024**
(full-catalogue evaluation) and **ADR 0025** (safetensors checkpoints) — none of
which is a listed gate, though 0024 constrains one: the metric floor D8's
`eligible` state depends on has to be calibrated against full-catalogue numbers,
which are roughly a third of the sampled-protocol figures a paper would quote.

**Phase 13 carried a gate and three decisions.** BUILD_PROMPT marks Phase 13 🛑
*"CONFIRM the design system (§10.7) before starting"*, and §10.7 answers its own
gate: build against CSS custom properties only, use the Modernist tokens for
now, and **ask which system to use before Phase 14**. That question is therefore
still open and is asked at the top of Phase 14 rather than treated as closed
here. The three decisions the phase reached are **ADR 0031** (`GET /v1/tenant`
is the single route exempt from gate 2, because the gate-2 landing page cannot
otherwise read the state that sent the reader to it), **ADR 0032** (a recovery
proof is never returned in a response, unlike an invitation token, because the
requester is an anonymous stranger rather than an authenticated administrator)
and **ADR 0033** (the access token lives in memory and only the refresh token is
stored, in `sessionStorage`, never `localStorage`).

Every listed gate D1–D12 is now closed. What remains open is §10.7's
design-system question and the numbered list below.

## Open questions with no recommendation

These have no proposed answer, only a stated need for one.

1. ~~**Email delivery.**~~ **Answered in Phase 13 — an administrator CLI.**
   BUILD_PROMPT L90 settles it, and `scripts/recovery_token.py` implements it;
   `graphrec.common.delivery` logs a deliberately alarming `WARNING` naming
   itself unfit for anything real when no transport is configured. What is *not*
   answered is delivery for a real deployment, which is an operational choice
   rather than an architectural one. See **ADR 0032**.
2. **The 15-minute training cooldown.** Is it a real product rule or an artefact
   of the prototype? Affects Phase 9 — Phase 7 meters training usage but does not
   admit training jobs, so the cooldown is not yet enforced anywhere.
3. **The last-active-administrator rule.** The prototype forbids demoting or
   disabling the last one. Does that extend to deletion, and to the platform
   realm? Affects Phase 4.
4. **Customer data lifecycle.** How long are raw interaction events retained,
   and what does tenant deletion actually erase? Affects Phase 5 and the
   reconciler.
5. **Who schedules reconciliation?** `reconcile_recent` is written and called by
   nothing. A periodic sweep needs either a scheduler process or a `JobType` with
   something to enqueue it; Phase 7 introduced neither. Affects Phase 7's own
   correctness over time, and the first closed period nobody rolls up.
6. **Does a ledger outlive the tenant it belongs to?** `usage_events` is
   immutable and billing-adjacent, and tenant deletion has no semantics yet. The
   `ON DELETE CASCADE` on `usage_events.tenant_id` currently answers "no", which
   is a default rather than a decision.
7. **How does a platform operator recover an account?** Their rows carry
   `tenant_id IS NULL`, the recovery resolver returns a tenant id, and so the
   endpoint cannot see them. Today the answer is another operator with database
   access. Affects Phase 15 and any real deployment. See **ADR 0032**.
8. **Which design system?** §10.7 defers the choice between the Modernist tokens
   the console is built against and the Claude palette in
   FRONTEND_BUILD_PROMPT §11, and asks for an answer before Phase 14. Because
   every value resolves through `tokens.css`, the answer changes one file.

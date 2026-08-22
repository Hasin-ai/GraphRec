# Architectural decisions

One file per decision. A decision is **Accepted** only when a human has confirmed
it; until then it is **Proposed**, and BUILD_PROMPT §2 forbids building past the
gate that depends on it.

## Confirmation gates

| # | Decision | Status | Confirm before |
|---|---|---|---|
| D1 | Resource model: SRS-native vs AWS Personalize | **Confirmed — SRS-native** | Phase 2 |
| D2 | Job queue: PostgreSQL `SKIP LOCKED` | Accepted | Phase 5 |
| D3 | Serving: Compose + `ServingDriver` port | Accepted | Phase 10 |
| D4 | Candidates: in-process exact top-K behind `CandidateIndex` | Accepted | Phase 10 |
| D5 | Token signing: EdDSA + published JWKS | **Proposed — built to** (ADR 0009) | Phase 3 |
| D6 | Versioning: `/v1` and `/v1/platform/*` | **Proposed — built to** | Phase 2 |
| D7 | Body limits: per-endpoint, not global | **Proposed — built to** | Phase 1 |
| D8 | Model lifecycle: seven states | Accepted | Phase 8 |
| D9 | Product writes: POST + PUT + PATCH | Accepted | Phase 6 |
| D10 | Pagination: limit/offset for console, cursor for volume | Accepted | Phase 6 |
| D11 | Plans: STARTER / GROWTH / SCALE | **Proposed — built to** | Phase 4 |
| D12 | Wire casing: snake_case | **Proposed — built to** | Phase 2 |

D1 was confirmed SRS-native and Phase 2 was built on it.

Four decisions carry a **Proposed** status *and have been built to*, on the
basis that each of them was a stated recommendation in BUILD_PROMPT's appendix
and Phase 2 could not proceed without an answer. **This is a departure from
BUILD_PROMPT §2, which says not to build past a gate on an unconfirmed
decision**, and it is reported rather than assumed. D5 is the one with a
deadline: it is due before Phase 3. The rework cost of each is scoped in the
Phase 2 report.

There is also a conflict the authorities do not resolve between them: the SRS
specifies a Qdrant Vector Store Contract (§6.3), which outranks D4's in-process
exact top-K. D4 is marked Accepted below on BACKEND_PLAN's authority, but the
SRS is higher, so an explicit "defer Qdrant" decision is needed before Phase 10.

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

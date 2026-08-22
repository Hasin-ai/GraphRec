# Architectural decisions

One file per decision. A decision is **Accepted** only when a human has confirmed
it; until then it is **Proposed**, and BUILD_PROMPT §2 forbids building past the
gate that depends on it.

## Confirmation gates

| # | Decision | Status | Confirm before |
|---|---|---|---|
| D1 | Resource model: SRS-native vs AWS Personalize | **Proposed — blocking** | Phase 2 |
| D2 | Job queue: PostgreSQL `SKIP LOCKED` | Accepted | Phase 5 |
| D3 | Serving: Compose + `ServingDriver` port | Accepted | Phase 10 |
| D4 | Candidates: in-process exact top-K behind `CandidateIndex` | Accepted | Phase 10 |
| D5 | Token signing: EdDSA + published JWKS | **Proposed** | Phase 3 |
| D6 | Versioning: `/v1` and `/v1/platform/*` | **Proposed** | Phase 2 |
| D7 | Body limits: per-endpoint, not global | **Proposed — built to** | Phase 1 |
| D8 | Model lifecycle: seven states | Accepted | Phase 8 |
| D9 | Product writes: POST + PUT + PATCH | Accepted | Phase 6 |
| D10 | Pagination: limit/offset for console, cursor for volume | Accepted | Phase 6 |
| D11 | Plans: STARTER / GROWTH / SCALE | **Proposed** | Phase 4 |
| D12 | Wire casing: snake_case | **Proposed** | Phase 2 |

Five decisions carry a **Proposed** status into Phase 2. D1 is the blocking one:
it determines the shape of every table, route and console URL, and BUILD_PROMPT's
appendix is explicit that no code should be written against it until it is
answered.

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

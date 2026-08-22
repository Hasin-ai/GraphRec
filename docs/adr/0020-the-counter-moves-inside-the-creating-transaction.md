# ADR 0020 — The fast counter is incremented inside the creating transaction

**Status:** Accepted
**Phase:** 7
**Gate:** none.

## Context

Quota enforcement runs inside the transaction that creates the thing being
metered (BUILD_PROMPT 7.5, ER-F-11), reading a Redis counter rather than summing
a month of `usage_events`. The grant is written to the ledger in that same
transaction. The counter is not: Redis is not in the transaction and cannot be
rolled back with it.

So the increment has to go either inside — where a rollback leaves it high — or
after the commit, where a crash between the two leaves it low.

Placing it after the commit is not a small change here. The transaction boundary
is `async with sessionmaker() as bound, bound.begin():` in `deps.py`, with the
`yield` inside it, so all handler code runs pre-commit by construction. A
post-commit hook means threading a callback list through two frozen, slotted
principal dataclasses and both authentication realms.

## Decision

Increment next to the ledger insert, inside the caller's transaction. A rolled
back grant leaves the counter high until the next reconciliation.

## Consequences

* The failure direction is chosen, not conceded. A counter that is high refuses
  a tenant slightly early — visible, appealable, and corrected by the next
  rollup. A counter that is low hands out allowance nobody recorded, and nothing
  detects it until the invoice.
* `ledger.grant` returns a boolean and the counter moves only when it is `True`,
  so a retried transaction re-attempting the same idempotency key moves nothing.
* The rollup is what makes this survivable, and it is currently scheduled by
  nothing (Phase 7 report §5). Until it is, a drifted counter stays drifted for
  the rest of the period.
* `counters.py` documents the tradeoff in its module docstring rather than in a
  commit message.

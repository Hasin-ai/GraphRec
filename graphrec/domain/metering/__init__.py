"""Metering: what a tenant used, what they are allowed, and what we don't know.

The phase's shape, in the order a number moves through it:

* `periods` — the monthly window, half-open, UTC, and the labels for it.
* `ledger` — `usage_events`. Append-only, idempotent, written inside the
  transaction that creates the thing being metered.
* `counters` — the Redis mirror that makes the quota check affordable, and the
  rule that a cache miss is repaired from the ledger rather than read as zero.
* `sources` — where each usage type's number comes from, and the registry that
  turns "no source yet" into `measurement delayed` rather than into `0`.
* `rollup` — reconciliation. Recomputes the counters and
  `monthly_usage_aggregates` from the ledger, which is the only copy that cannot
  have been edited.
* `quota` — usage against limit, and the 429 that names both.
* `service` — the three reads the console's usage page makes.
"""

from __future__ import annotations

__all__: list[str] = []

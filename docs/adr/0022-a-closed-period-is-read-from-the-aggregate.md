# ADR 0022 — A closed period is read from the aggregate; the open one is measured live

**Status:** Accepted
**Phase:** 7
**Gate:** none.

## Context

The usage page shows the current period; the trend panel shows three (dc.html
L1818). The current period is still moving. The two before it are not.

Two of the six usage types are levels rather than totals — `products` and
`storage` are counted as they stand, not accumulated. A level has no history in
the tables it is measured from: the catalogue knows how many products exist now
and nothing about how many existed in June.

## Decision

The open period is measured live — the fast counter for accumulated types, a
live count for the catalogue. A closed period is read from
`monthly_usage_aggregates`, which is what the rollup wrote down.

A closed period with no aggregate row returns `None` from
`rollup.stored_measurement`, and `service.trends` renders that as `delayed`.

## Consequences

* `None`, zero and a status are three distinct things and stay distinct.
  "We never rolled up June" is not "June was zero", and the query returns the
  first rather than deciding it means the second.
* Historical figures are only as good as the rollup that recorded them, which is
  the honest position: for a level, the aggregate is the *only* record, and
  pretending otherwise would mean recomputing June's product count from a table
  that has no June in it.
* Nothing currently schedules the rollup (Phase 7 report §5), so today every
  closed period trends as a gap. Correct, and not yet useful.
* `reconcile_period` passes `live=False` so it never launders a drifted counter
  into the aggregate. Reconciliation must not trust the thing it is reconciling.

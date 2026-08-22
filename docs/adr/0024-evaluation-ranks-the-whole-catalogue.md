# ADR 0024 — Evaluation ranks the whole catalogue, not sampled negatives

**Status:** Accepted
**Phase:** 8
**Gate:** none.

## Context

There are two conventions for offline top-K evaluation of a recommender.

The **sampled** protocol scores the held-out item against 100 random negatives
and asks where it lands among 101. It is cheap, it is what most published
numbers use, and it produces flattering figures — Recall@10 near 0.6 is
unremarkable under it.

The **full-catalogue** protocol scores the held-out item against every item the
tenant sells. It is what the served system actually does, and it produces much
lower numbers.

Phase 8's exit criterion is a comparison against a popularity baseline, and
Phase 10 will turn these same metrics into an eligibility floor that decides
whether a tenant's model version may be deployed. A floor calibrated on the
sampled protocol would admit models that disappoint in production, and the
disappointment would be attributed to serving rather than to the metric.

## Decision

Evaluation ranks the full catalogue, excludes the user's interaction history,
holds out one item per user by time, and macro-averages across users. The
popularity baseline is scored under the identical protocol.

`Metrics.beats` requires strictly better Recall **and** NDCG. Coverage is
reported alongside but is not part of `beats`, because a model can trade
accuracy for coverage and the trade is a product decision rather than a
correctness one.

## Consequences

* The numbers are low and comparable to production. On the Phase 8 fixture the
  model scores Recall@10 ≈ 0.52 against the baseline's ≈ 0.21; under a sampled
  protocol both would read far higher and the gap would compress.
* Evaluation costs `n_users` by `n_items` scores. At tenant scale that is a
  matrix multiply against the exported item matrix, which is the same operation
  serving performs, so the cost is bounded by the same thing.
* Recall@10 and HR@10 are numerically identical under leave-one-out. Both are
  reported because the console shows both; the equality is stated in the module
  docstring and pinned by `test_recall_equals_hit_rate_under_leave_one_out`
  rather than left for a reader to rediscover as a suspected bug.
* The metric floor Phase 10 writes must be calibrated against numbers from this
  protocol. A floor imported from a paper would be roughly three times too high.

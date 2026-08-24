# ADR 0041 — The reconciler is the only publisher of estate-wide gauges

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

Two of §24's alerts read gauges that describe the whole estate rather than one
process: `graphrec_serving_replicas{tenant_id,state}` behind
`TenantHasNoReadyReplica`, and `graphrec_job_queue_depth{job_type,status}` with
`graphrec_job_queue_oldest_seconds` behind `JobQueueDeep` and `JobQueueStalled`.

A gauge is a per-process value. Prometheus keeps one series per target, so if
every process that knows the queue depth published it, the same fact would
arrive from the control API, from both job workers and from the reconciler, as
four series that differ by which instant each process last looked. Every
expression over them then needs an aggregator, and the two obvious ones are both
wrong: `sum` multiplies the queue by the number of publishers, and `max` is
correct until a publisher's Redis lookup is stale and it becomes the maximum.

The version of this that actually bites is `ready_replicas`. An inference
replica knows whether *it* is ready. It does not know how many of its siblings
are, and a replica that published the tenant's ready count would be publishing a
guess — one that reads as authoritative and goes wrong in exactly the case the
alert exists for, because a replica that has crashed publishes nothing at all
and its absence makes the count look better rather than worse.

## Decision

**One publisher per estate-wide gauge, and it is the process that already
computes the number as part of its job.**

* `graphrec_serving_replicas` — the reconciler, in its convergence pass. It
  compares desired against ready for every tenant on every pass; the gauge is
  that comparison, written down.
* `graphrec_job_queue_depth` and `graphrec_job_queue_oldest_seconds` — also the
  reconciler, which already sweeps expired leases across the whole queue.

Per-process metrics stay per-process: `graphrec_http_in_flight`,
`graphrec_inference_ready` for the replica's own binding, request histograms.
Those are meant to be one series per target and are aggregated in the query.

## Consequences

**The reconciler is a single point of measurement, and it is not redundant.**
If it stops, the gauges stop being written, and a gauge that stops being written
does not go to zero — it goes stale, holds its last value for `TargetDown`'s
window and then disappears. `TenantHasNoReadyReplica` cannot fire on a series
that is gone, so the alert that covers a tenant losing its replicas is itself
covered only by `TargetDown` on the reconciler. That is a real gap and it is why
`TargetDown` is one of the nine rules rather than a nicety.

The gauges are only as fresh as `RECONCILE_INTERVAL_SECONDS` (5 s by default).
The alert windows are minutes, so this does not matter for alerting; it does
mean the Grafana panel for replicas is a five-second-old view and will not
animate a scale-up smoothly.

The reconciler is serial and scheduled by nothing but its own loop — carried
forward as a known limitation from earlier phases. That limitation now has a
second consequence: a slow pass delays the metrics as well as the convergence.

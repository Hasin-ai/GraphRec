# ADR 0019 — A usage type is measured because a source is registered for it

**Status:** Accepted
**Phase:** 7
**Gate:** none.

## Context

BUILD_PROMPT's exit criterion for metering is that "a delayed measurement
renders as a status rather than a zero", and the prototype states the same rule
as page copy: *"An unavailable measurement is stated, never shown as a zero"*
(dc.html L1805), with "Service capacity is measured continuously; the current
reading is delayed, so remaining allowance is not calculable" underneath the
table (L1824).

Six usage types, and two of them cannot be measured at all before Phase 11:
`storage` needs object storage and `service_capacity` needs the serving
reconciler. The obvious implementation is a branch in the view — *if the type is
storage or service capacity, report delayed* — and it has two failures. It is a
list of exceptions that has to be found and deleted in Phase 11, and it puts the
rule in the one layer that also has a `0` conveniently to hand.

## Decision

`MEASUREMENT_SOURCES` maps a usage type to the function that measures it.
`measure()` looks the type up; a type with no entry returns
`Measurement.delayed()`. There is no list of undelayed types anywhere, because
the registry's keys are that list.

`Measurement` enforces the pairing in its constructor — a `measured` status has
a quantity, and no other status does — and `monthly_usage_aggregates` enforces
the same thing with `CHECK ((measurement_status = 'measured') = (quantity IS NOT
NULL))`. An impossible pair cannot be constructed in Python and cannot be stored
in Postgres.

## Consequences

* Phase 11 registers a prober and the row becomes measured. Nothing in
  `service.py`, the router or the schemas changes.
* `test_a_usage_type_with_no_source_is_delayed_by_construction` asserts the
  unsourced set is exactly `{storage, service_capacity}`. It fails when Phase 11
  lands, which is intended: it is the reminder that the docstrings naming Phase
  11 need updating too.
* Every reader of a `Measurement` can trust `status` and `quantity` to agree, so
  no view checks both. `service.py` contains no `or 0`, and the module docstring
  says the absence is the feature.
* The cost is one dictionary lookup per row per request, and a registry that
  must be kept in step with `UsageType`. A type added to the enum and not to the
  registry reports as delayed — which is the right default, but it is silent.

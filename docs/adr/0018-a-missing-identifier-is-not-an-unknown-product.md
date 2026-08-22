# ADR 0018 — A missing product identifier is not an unknown product

**Status:** Accepted
**Phase:** 6
**Gate:** none.

## Context

Found by a test, not by review. `normalise_event` raised `item_unknown_product`
for an event whose `external_product_id` was absent or over-length — the same
code the merge raises for an identifier that names nothing in the tenant's
catalogue.

The validator has not looked in the catalogue and is in no position to say
anything about what is in it. Worse, the conflation was load-bearing:
`_single_event_error` routes a per-item code to the field error the single-event
form renders, and an item that never carried an identifier was being reported to
the tenant as a catalogue problem.

The two defects have different fixes in different systems. A missing identifier
is fixed in the tenant's exporter. An unknown identifier is fixed in the
tenant's catalogue — the product is genuinely not there. Telling them apart is
the entire value of a per-item error row.

## Decision

Three codes where there was one:

* `item_product_id_missing` — *"product identifier is missing"*
* `item_product_id_too_long` — *"product identifier exceeds 120 characters"*
* `item_unknown_product` — unchanged; raised by the merge, after a real lookup.

The first two are shape verdicts and are raised before any catalogue access. The
third is a catalogue verdict and can only be raised by something that queried it.
`_single_event_error` maps the two new codes onto `event_identifiers_required`
on the `external_product_id` field, which is the marker the prototype's form
renders.

## Consequences

* `ITEM_ERROR_COPY` gains two entries. Both follow the item-copy convention —
  lower case, no full stop — because they are rendered in a table cell beside
  the item reference, not as a banner.
* The rule generalises: a validator that runs before a lookup must never emit a
  code that asserts the result of that lookup. This is now covered by
  `test_every_code_the_validator_can_raise_has_approved_copy`, which fails if a
  new code is raised without copy, but it does not by itself catch a *wrong*
  code — that took a test that asserted the tenant-visible field.

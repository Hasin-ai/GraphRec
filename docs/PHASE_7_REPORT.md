# Phase 7 — Metering

**Scope (BUILD_PROMPT L647-648):** `usage_events` (INSERT-only grant),
`monthly_usage_aggregates` · Redis fast counters + durable ledger +
reconciliation rollup · effective-limit resolution (plan, then active override) ·
`GET /v1/usage`, `/trends`, `/subscription` **with `measurement_status`** ·
quota checks inside creating transactions.

**Gate:** none. The next gate is D4/D8 before Phase 10.

## 1. Built

* **Schema** — `migrations/versions/0009_metering.py`. `usage_events` granted
  `SELECT, INSERT` to `graphrec_app` and nothing more; `monthly_usage_aggregates`
  with `quantity` nullable, `measurement_status` not, and the check that ties
  them together: `(measurement_status = 'measured') = (quantity IS NOT NULL)`.
  Both under RLS with `FORCE`; the aggregates additionally readable by
  `graphrec_platform`.
* **Domain** — `graphrec/domain/metering/`, six modules with one job each:
  `periods` (half-open UTC months and the console's reset copy), `ledger`
  (idempotent grants, no update path), `counters` (the port, three adapters, and
  `current` which repairs a miss from the ledger), `sources` (the measurement
  registry — ADR 0019), `rollup` (assignment, not increment), `quota` (usage
  against limit, inside the caller's transaction), `service` (the three reads).
* **Limit resolution** — `graphrec/domain/quotas.resolve()` now returns a `Limit`
  carrying its `source`, in the documented precedence: active override, standing
  tenant quota, plan. `effective_limit()` delegates to it, so there is one
  lookup rather than two that can disagree.
* **Request surface** — `apps/control_api/routers/usage.py`: `GET /v1/usage`,
  `GET /v1/usage/trends`, `GET /v1/subscription`, all administrator-only
  (L650, L1256). Every nullable field passes through as `null`.
* **Wiring** — `ResilientUsageCounters(RedisUsageCounters(...))` on
  `app.state`, closed in the lifespan teardown; `JobContext` and `Worker` carry
  counters so the batch path meters the same way the synchronous path does.
* **Copy** — three derived `usage quotas` entries following
  `training_quota_exhausted`'s shape and `product_quota_exhausted`'s counts.

## 2. Verified

* `ruff format`, `ruff check`, `mypy graphrec apps` (81 source files) and
  `lint-imports` (3/3 contracts) all clean.
* **618 tests pass** against a real PostgreSQL 18 with `GRAPHREC_REQUIRE_DB=1`,
  74 of them new in `tests/metering/` and 8 in
  `tests/contract/test_migration_literals.py`.
* **The exit criteria, each as a named test:**
  * `test_update_on_usage_events_raises` — and
    `test_delete_on_usage_events_raises` beside it, because a ledger you can
    empty is not more honest than one you can edit.
  * `test_a_delayed_measurement_renders_as_a_status_rather_than_a_zero`.
* Also held: the rollup is idempotent and reads the ledger rather than the
  counter it is correcting; a drifted counter is reassigned to the ledger's
  figure; an unreachable Redis degrades to the ledger rather than to zero
  (verified for real — Redis is not running on this machine, and every metering
  test passes through the `ConnectionError` path); override beats plan, and
  revoked or expired overrides do not; a refusal names usage, limit, plan and
  reset date; a duplicate event is confirmed and not charged twice; a batch is
  charged for what it merged, not what it submitted; a 429 at the ingest route
  leaves `interaction_events` unchanged.
* **Migration roundtrip** — `downgrade 0008` then `upgrade head` against the
  live database, after which the grant table reads
  `usage_events → graphrec_app: INSERT,SELECT`.

## 3. Defects found and fixed

* **Two tests were silently vacuous.** `test_an_exhausted_quota_refuses_the_write`
  counted `interaction_events` through `owner_engine`, which `FORCE ROW LEVEL
  SECURITY` fences out of the table: the count was `0` before and after, so
  "no row was written" passed without anything being written. Found because the
  sibling assertion about `usage_events` failed for the same reason and was not
  vacuous. Both now read as `graphrec_app` inside the tenant's context, and the
  test asserts `before > 0` so it cannot regress to vacuity.
* **The test suite leaked event loops.** Synchronous tests driving the HTTP
  client called `anyio.run` for their database assertions, leaving unclosed
  loops and sockets that surfaced later as `PytestUnraisableExceptionWarning`
  attributed to whichever test happened to be running — one full-suite run
  failed on it. Database reads are now synchronous, and the two tests needing
  the async worker are async tests that call the blocking client through
  `anyio.to_thread`.
* **`GraphRecError` has no `details` object.** `quota.assert_within` was written
  to attach the numbers structurally. Corrected to carry them in `copy_args`,
  the way `product_quota_exhausted` already does; the module docstring now says
  so rather than leaving the next reader to rediscover it.
* **Two migrations cited a contract test that did not exist.** 0007 and 0008
  both claimed their literals were "pinned by a contract test that compares the
  two"; nothing compared them. `tests/contract/test_migration_literals.py` now
  does, for all three migrations, and the comments name the file.

## 4. Decisions recorded

| ADR | Decision |
| --- | --- |
| 0019 | A usage type is measured because a source is registered for it; absence from the registry *is* the delayed status. |
| 0020 | The fast counter is incremented inside the creating transaction, failing high rather than low. |
| 0021 | A standing `tenant_resource_quotas` row reports on the wire as `override`; there is no third `limit_source`. |
| 0022 | A closed period is read from `monthly_usage_aggregates`, the open one measured live. |

**0019** — `MEASUREMENT_SOURCES` maps a usage type to the function that measures
it. `storage` and `service_capacity` have no entry until Phase 11, so `measure`
returns `Measurement.delayed()`, and `Measurement.__post_init__` (mirrored by
`ck_mua_measured_iff_quantity`) makes a status/quantity mismatch
unconstructible. The alternative — a special case in the view — would have to be
found and removed in Phase 11; this becomes correct by registering a function.

**0020** — the increment happens next to the ledger insert, which Redis cannot
be rolled back with, so a transaction that grants and then fails leaves the
counter high until reconciliation. Chosen over deferring past the commit: a high
counter refuses a tenant slightly early, which is visible and appealable, while
a low one hands out allowance nobody recorded. The alternative needed a
post-commit hook threaded through two frozen principal dataclasses and both auth
realms, to buy a correction the rollup already makes.

**0021** — BACKEND_PLAN L1195 gives two wire values and the schema has three
sources. From the tenant's side a standing per-tenant quota *is* an override: a
limit that is not the one their plan states. Splitting them would ask the
console to explain a distinction that exists only in our schema.

**0022** — the open period still moves, so it is measured live; a closed one has
stopped, and a point-in-time level like the product count has no history other
than the one the rollup wrote down. A closed period that was never rolled up
reports as `delayed`, not as zero.

## 5. Not done

* **Nothing schedules the rollup.** `reconcile_recent` is written, tested and
  called by nothing. It needs a periodic job, which means either a scheduler or
  a `JobType`, and Phase 7 introduced neither. Until then
  `monthly_usage_aggregates` is populated only by tests, and a closed period
  trends as a gap — correct, but permanently so.
* **Training and recommendation usage are never granted.** `QUOTA_COPY` and the
  limit resolution cover all three accumulated types; only `events` has a
  caller. Phases 9 and 11 are the ones that charge.
* **`training_quota_exhausted` does not name limit and usage.** BACKEND_PLAN
  L1840 asks every rejection to; the prototype writes that sentence itself
  (L1647) and it names only the reset. Approved copy outranks the plan, so the
  arguments are supplied and go unused. Pinned by
  `test_training_keeps_its_own_verbatim_sentence` so the divergence is
  deliberate rather than forgotten.
* **`InMemoryUsageCounters` overshoots across replicas.** Documented in the
  module: two API processes each hold their own count and each admit a tenant to
  the limit. It is a single-process adapter; the deployed path is Redis.
* **Redis has never run in this environment.** Every test exercises the
  degraded path, which is a real and useful result, but `RedisUsageCounters`
  itself — `INCRBYFLOAT` on an existing key, the TTL — has not executed against
  a server.
* **Carried forward from Phase 6, still open:** `product_concurrent_change`
  (dc.html L1335) is approved copy with no mechanism, now deferred three times;
  CI has never executed; the Docker stack is unverified since Phase 3; Qdrant
  vs D4 needs an explicit defer before Phase 10; retention and tenant deletion
  remain unanswered — and a tenant deletion now has `usage_events` to consider,
  which is a ledger and probably should outlive the tenant.

## 6. New conflicts

One, and it is the copy divergence in §5 rather than a contradiction between
sources: BACKEND_PLAN L1840 and dc.html L1647 want different things from the
training refusal, and the prototype wins. Recorded rather than resolved, because
resolving it means rewriting approved copy.

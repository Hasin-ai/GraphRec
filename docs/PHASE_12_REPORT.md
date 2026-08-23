# Phase 12 — Audit and platform

**Scope (BUILD_PROMPT L671-673):** `audit_logs`, `security_events` with
append-only grants · audit writes on every ER-F-11 action · `GET /v1/audit-logs`
tenant-scoped and redacted · platform permission dependency · all 13
`/v1/platform/*` endpoints including the three-section composed tenant detail ·
`GET /v1/platform/status` with `measurement_gaps`.

**Done when:** tenant audit never reveals another tenant, and a partially-
permitted platform user sees withheld sections rather than a `403`.

**Gate:** none. BUILD_PROMPT marks no 🛑 on this phase. Two decisions were made
anyway and recorded as **ADR 0029** and **ADR 0030**.

## 1. Built

~3,700 lines across schema, two domain packages, two routers and the tests.

* **`migrations/versions/0013_audit.py`** (350) — `audit_logs` and
  `security_events`, both `FORCE`d. The phase's central rule is expressed as an
  *absence*: no `UPDATE` and no `DELETE` is granted on either table, to either
  runtime role, ever. Append-only is therefore a property of the grants rather
  than of a trigger somebody can drop or a convention somebody can forget.

  Both tables carry **four policies rather than one**, which is unlike every
  other table in the schema. Everywhere else a tenant may read exactly what it
  may write, so one `FOR ALL` policy with matching `USING` and `WITH CHECK` is
  right. Here the application role must be able to record an event it cannot
  attribute — a sign-in refused for an address belonging to no tenant — and must
  never read one back. So `FOR SELECT` filters on `tenant_id = current_setting(…)`
  while `FOR INSERT` also admits `tenant_id IS NULL`. The platform realm gets its
  own `USING (true)` pair, because it never sets `app.tenant_id`: tenant is a
  filter there, never a scope.

* **`graphrec/db/models/audit.py`** (97) and **`graphrec/domain/audit/`** (762) —
  `record` (the writer, called inside the transaction that performs the thing
  being recorded), `query` (two projections for two audiences), `trail` (the
  handler-facing `AuditTrail`, `action()` context manager and `refused()`).

  `query` is two functions rather than one with a flag. A flag puts the
  redaction rule one boolean away from being wrong, and SRS §5.2.16 makes the
  tenant-facing view specifically the one that must never carry another tenant's
  data or any hint that another tenant exists. `AuditRow` has six fields;
  `actor_id`, `details`, `tenant_id` and `correlation_ref` are not among them,
  and there is no code path that can add them.

* **`graphrec/domain/platform/`** (1,393) — `tenants` (the estate, the composed
  detail, status changes, plan assignment, quota overrides), `plans` (the price
  list), `usage` (cross-tenant aggregates), `status` (the board).

  `Section[T]` is the shape ADR 0030 describes: `{granted, data, reason}`, with a
  `payload` property that raises rather than returning `None` so a router that
  reads a withheld section fails at the mistake instead of serialising a null.

* **`apps/control_api/routers/platform.py`** (669) — 15 handlers on the 13
  paths, with five permission dependencies (`platform`, `plan_management`,
  `platform_scope`, `monitoring`, `audit`). **`routers/audit.py`** (81) — one
  administrator-only read, deliberately almost empty: everything it must never
  do is enforced by RLS and by the projection, not by a condition in the handler.

* **`graphrec/domain/platform/status.py`** (338) — the board, and the reason it
  exists as its own module is that the platform role holds no grant on
  `submissions` or on any training table. So `ingestion_lag` comes from
  `jobs.run_after` for queued ingestion types, `training_queue` from `jobs`,
  `replicas` from the six granted columns of `model_deployments`,
  `serving_availability` from the six granted columns of
  `recommendation_requests`, and the failure counts from `security_events`. No
  new grant was needed to build the page, which is the check that the grant list
  was drawn correctly in the first place.

* **Security events are now raised by the things that fail.** Terminal job
  failures (`graphrec/jobs/worker.py`), the transition into `degraded` and
  failed activations (`domain/serving/reconciler.py`), and serving refusals
  (`domain/serving/recommend.py`). Each is deliberately narrow — only terminal
  failures, only the transition rather than every pass, only refusals rather
  than fallbacks — because a board that fills with rows for work that then
  succeeded is a slower way of having no monitoring at all.

* **Suspension now reaches the containers.** The platform role holds no write on
  `model_deployments`, deliberately, so suspending a tenant changes
  `tenants.status` and nothing else. The reconciler reads that status on its
  sweep and converges a suspended tenant to zero via `DeploymentService.halt`;
  `resume` restores the floor for a reactivated tenant that still has an active
  version, so reversibility is a property rather than a word.

## 2. Verified

**1,082 tests pass**, 50 of them new in `tests/audit/` and `tests/platform/`,
plus four in `tests/serving/test_reconciler.py` and `tests/jobs/test_worker.py`.
All five gates green: `ruff format --check`, `ruff check`, `mypy` (156 files,
strict), `lint-imports` (3 contracts), full pytest with `GRAPHREC_REQUIRE_DB=1`.

**The exit criterion, in two halves.**

*Tenant audit never reveals another tenant* —
`tests/audit/test_tenant_visibility.py` seeds three rows a moment before the
read: one for the caller, one for a stranger, one attributable to nobody. The
caller's page contains the first and neither of the others. A fourth test pins
the response's *exact* key set rather than asserting the absence of `actor_id`,
because an inequality passes for a response that has grown `details` instead.

*A partially-permitted platform user sees withheld sections* —
`tests/platform/test_tenant_detail.py` walks the combinations: everything held,
each section withheld in turn, and only the base permission. In every case the
status is `200`, the withheld section's `data` is `null` — not an empty object,
which would be indistinguishable from a tenant who has used nothing — and its
`reason` is the sentence from `WITHHELD_SECTION_COPY`. The counter-case is
asserted too: an operator holding only `audit` gets `403` from the route, because
a page of three withheld sections is itself a confirmation that the tenant
exists.

**Append-only, asserted twice.** `tests/audit/test_append_only.py` asks the
catalogue what the grants are *and* runs the statements. The catalogue check
localises a regression to the migration that caused it; the live attempt catches
a grant restored somewhere the catalogue check does not look, such as a
`GRANT … ON ALL TABLES` in a later migration.

**Measurement gaps, asked about a chosen instant.**
`tests/platform/test_measurement_gaps.py` calls the domain directly with
`now = 2099-01-01`, which makes "no request was served in this window" certain
rather than likely. Both directions are asserted: a null quantity always has a
gap, and a measured quantity never appears as one — a board that shows a number
*and* says it could not be obtained is a board nobody trusts twice. Zero
deployments is asserted to be a *measured* zero, not a gap.

## 3. Decisions and deviations

**ADR 0029 — a refused action is audited on a second connection.** A refusal
raises, the raise unwinds the request's transaction, and the rollback takes the
row explaining the refusal with it. Writing into the doomed transaction produces
no row at all. So refusals commit separately and immediately, and the audit
write is wrapped so that it can never convert a refusal into a 500. The cost is
a pool connection on a path that has already decided to fail, and a refusal row
that can outlive a request which then failed for an unrelated reason. Both are
the cheap direction: the refusals are the rows an investigation looks for.

**ADR 0030 — a withheld section is a page, not a `403`.** Described above and in
the ADR. The one consequence worth repeating here is that the withheld sentence
comes from the copy catalogue rather than from the console, so the console never
composes its own explanation of an authorization decision.

**A platform action concerning a tenant *is* visible to that tenant.** A
docstring in `routers/platform.py` claimed the opposite; the RLS policy says
otherwise and the policy is right. An account being suspended is something its
owner is entitled to see recorded. What they do not see is *who* did it:
`AuditRow` omits `actor_id`, so the tenant reads `platform_administrator` and a
timestamp. The docstring was corrected rather than the behaviour.

**The audit page offers two filters and deliberately not a third.** `action` and
`occurred_after` are offered; `resource_ref` is not. A reference filter lets a
caller ask "does this identifier exist" and read the answer off the row count,
which is the same oracle gate 4's indistinguishable 404 exists to close.

**Platform requests are now one transaction.** `current_platform_principal` held
a bare session, which was correct while the realm had nothing to commit. It now
suspends tenants, edits plans and grants overrides, and each of those has to
land with its audit row or not at all.

**Failures default to redacted.** `GET /v1/platform/failures` returns
`tenant_id: null` unless the caller passed a `tenant` — in which case they
already know which tenant they are looking at. It is not that the platform role
cannot read the column; it is that a severity ranking must not double as a
league table of which customers are struggling (L1550), and defaulting to
redacted is the only version of that rule which survives a hurried change.

## 4. Bugs this phase found in code written earlier

**Three tables' primary keys were never minted** (`domain/platform/tenants.py`,
`domain/platform/plans.py`). `pk_uuid()` declares a `gen_random_uuid()` server
default, and migration 0002 does not carry one for `tenant_subscriptions`,
`quota_overrides` or `pricing_plans`. The ORM model and the schema disagreed, so
the first assignment of a plan to a tenant died with a `NotNullViolation` — a
500 on one of the platform realm's most-used verbs. Fixed by minting `uuid7()`
at construction, which is also what every other domain module does and what the
audit row needs in order to name the thing that was created. Found by
`test_tenant_lifecycle.py::test_assigning_a_plan_moves_the_tenant_onto_it`.

**A stopped deployment kept reporting the replicas it used to have**
(`domain/serving/reconciler.py`). The zero-desired branch observes the driver,
tears down any live containers and mirrors the result into `serving_replicas` —
but never updated `model_deployments.ready_replicas`. `halt()` deliberately does
not touch that column, since only an observation may write it, so a suspended
tenant's row went on saying `ready: 1` after its containers were gone. That is
exactly the memory-dressed-as-a-measurement the status board was built to refuse
to render, arriving from the one place the board could not detect it. Found by
`test_reconciler.py::test_a_suspended_tenant_is_wound_down_and_its_containers_stopped`.

**A stopped deployment's containers were never torn down at all.** The same
branch previously returned without calling `driver.stop()`, so a deployment
wound down to zero left its replicas answering until somebody noticed them. Not
reachable before this phase — nothing set `desired_replicas` to zero — and
reachable the moment suspension did.

**A policy-shape test demanded something Postgres will not create**
(`tests/isolation/test_cross_tenant_reads.py`). The test looped over every
`graphrec_app` policy and required both `USING` and `WITH CHECK`. That is right
for a `FOR ALL` policy and impossible for the split policies migration 0013
needs: a `FOR SELECT` policy has no `WITH CHECK` and a `FOR INSERT` policy has no
`USING`. Rewritten to assert per command, and to assert the invariant that
actually matters — for every tenant-owned table, reading is filtered *and*
writing is checked — which is a stronger statement than the one it replaced.

**Owner deletes against a `FORCE`d table silently match nothing.** Not a product
bug but a fixture one, caught in this phase's teardown and worth recording
because it will recur: `DELETE FROM tenant_subscriptions` as the owner reports
success and removes no rows, and the subsequent plan delete then fails its
foreign key. The procedure migration 0002 documents — lift `FORCE`, act, restore,
in one transaction — is the only correct form, and it belongs in a `finally` in a
fixture and nowhere else.

## 5. Not done

**No audit retention or partitioning.** `audit_logs` is the one table nobody
prunes and nothing yet prunes it. Reads are bounded (limit capped at 200, newest
first, indexed) so this is a storage question rather than a latency one, but it
is unanswered — and it is entangled with the open question about whether a
ledger outlives the tenant it belongs to. The FK is `ON DELETE SET NULL` today,
which means a deleted tenant's history survives as unattributed rows: a default
rather than a decision.

**`security_events` has no alerting.** Rows are written and rendered. Nothing
watches the table, so a `critical` event is seen when an operator next opens the
page. XR-F-09's alerting story is not in this phase's scope and is not in any
later phase's either.

**The status board is per-installation, not per-node.** `replicas` sums across
every deployment, which is right for ASM-02's four tenants on one N3 and would
be misleading on the k3s adapter ADR 0028 defers.

**Staleness is a fixed five minutes.** `DEFAULT_STALENESS` is not configurable
and is not derived from the reconciler's actual sweep interval. If the sweep is
slowed, the board will start reporting a gap that is really a configuration
mismatch.

**`GET /v1/platform/status` recomputes on every request.** Nine queries, none
expensive, no caching. Fine at this size; the first thing to look at if the
admin console starts polling it.

**Still open from earlier phases:** the 15-minute training cooldown is
provisional; no retention sweep for orphaned artifacts; training concurrency is
per tenant rather than platform-wide; the metric floor is not tenant-configurable;
the training worker still takes the in-memory counter default; the reconciler is
serial; `serving_replicas` rows are not swept.

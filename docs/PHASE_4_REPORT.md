# Phase 4 report — Jobs

**Date:** 2026-08-22
**Status:** Complete. All three of BUILD_PROMPT's exit criteria are met and
pinned by tests. Three real concurrency defects were found by those tests and
fixed; a fourth was found in the cooperative-cancellation path. The gate (D2)
was closed by instruction rather than by an explicit answer, which §5 states
plainly rather than dressing up.

---

## 1. What was built

### Migration — `migrations/versions/0006_jobs.py`

One table, one schema, one role, two functions.

`jobs` carries the queue state (`status`, `priority`, `attempt`,
`max_attempts`, `run_after`), the lease (`lease_owner`, `lease_expires_at`), the
cancellation request (`cancel_requested_at`, `cancel_reason`) and the outcome
(`failure_code`, `failure_reason`, `progress`). Six `CHECK` constraints, of which
two are the interesting ones: `ck_jobs_terminal_has_completion` — a terminal job
has a `completed_at` — and `ck_jobs_running_holds_a_lease`, which makes "running
without a lease" unrepresentable rather than merely unlikely.

RLS `ENABLE` + `FORCE` + `USING` + `WITH CHECK`. `graphrec_app` gets `SELECT,
INSERT, UPDATE` and **no `DELETE`** — same reasoning as `api_keys`: the row that
explains a charge, or a missing recommendation, has to still be there when
somebody asks. `graphrec_platform` gets column-level `SELECT` on fifteen columns
and never on `payload`.

The fourth deliberate hole in default-deny lives here. **`graphrec_queue`** is
`NOLOGIN`, `NOINHERIT`, non-superuser, no `BYPASSRLS`; it owns the `job_queue`
schema and two `SECURITY DEFINER` functions with `search_path` pinned and
`EXECUTE` revoked from `PUBLIC`. It holds *no table-level grant at all* — nine
scheduling columns readable, five lease columns writable, and `payload` in
neither. See ADR 0011 for why the hole has to exist and §2 for what pins its
size.

`job_queue.claim(p_owner, p_job_types, p_lease_seconds)` returns
`(claimed_job_id, claimed_tenant_id)` and nothing else. `job_queue.expired_leases(p_limit)`
likewise. The worker takes those two identifiers, opens a *tenant-bound* session
and loads the job through the tenant's own policy — so the widened read never
becomes a widened disclosure.

The migration round-trips: `alembic downgrade 0005` then `upgrade head`,
verified against `pg_class`, `pg_policies`, `pg_proc`, `pg_indexes` and
`information_schema`.

### `graphrec/jobs/` (5 modules)

- **`states.py`** — `QueueStatus` (queued/running/succeeded/failed/cancelled) and
  `JobType`. Deliberately *not* in `graphrec/common/enums.py`, which is generated
  from the prototype: that file's `JobState` is the training stage rail, a
  different vocabulary that happens to overlap in two words.
- **`failures.py`** — the retry classifier. `classify(exc) -> Verdict`. A
  `PermanentJobError` names its own code; a `GraphRecError` is retried according
  to the `retryable` flag the error taxonomy already carries, so the queue and
  the API agree about what a transient failure is without a second table saying
  so. Backoff is `min(5 · 2^attempt, 300)` seconds.
- **`queue.py`** — `JobQueue`: enqueue, claim, load, heartbeat, report_progress,
  succeed, fail, finish_cancelled, request_cancellation, sweep_expired. Every
  write that assumes this worker still owns the job is guarded on
  `lease_owner = :owner AND status = 'running'` and raises `JobLeaseLost` when it
  matches nothing.
- **`handlers.py`** — `JobContext`, `JobHandler`, `HandlerRegistry`. The claim
  filter is *derived from* the registry, so a worker cannot claim a job type it
  cannot run, lease it, fail it and spend the tenant's attempts on a deployment
  mistake.
- **`worker.py`** — the claim loop, the heartbeat and the sweeper.

### `apps/job_worker/`

`main.py` builds the worker, installs `SIGINT`/`SIGTERM` → `request_stop()`
(drain, not abort) and runs. `registry.py` is empty, with comments naming what
Phases 6 and 7 will register — and the worker **refuses to start** with an empty
registry rather than running healthily while claiming nothing.

### `docker-compose.yml`

A `job_worker` service behind `profiles: ["workers"]`, with
`stop_grace_period: 150s` — longer than the 120s lease, so a deploy drains
in-flight jobs instead of manufacturing retries. Behind a profile *only* because
the registry is empty until Phase 6 and a service that crash-loops on a fresh
clone teaches everybody to ignore restarts.

---

## 2. What was verified, and how

`tests/jobs/` (65 tests) and `tests/isolation/test_queue_role.py` (15). Full
suite: **336 passed**, `ruff` clean, `mypy graphrec apps` clean on 57 files.

**The three exit criteria, each by name:**

| BUILD_PROMPT:636 | Test |
|---|---|
| two workers claim disjoint jobs | `test_claim.py::test_two_workers_claim_disjoint_jobs` — six concurrent claims over six jobs, asserts six distinct results |
| a killed worker's job requeues automatically | `test_lease.py::test_a_killed_workers_job_requeues_automatically` |
| a deterministic failure consumes no attempts | `test_retry.py::test_a_deterministic_failure_consumes_no_attempts` |

**Properties pinned that would otherwise be invisible:**

- **The queue role cannot read a `payload`.** `test_queue_role.py::test_the_queue_role_never_sees_a_payload`
  asserts the readable column set *exactly*, and a companion test asserts the
  role holds no table-level grant — because a table-level `SELECT` silently
  includes every column added later, which is how a `payload` exclusion decided
  once stops holding.
- **The claim returns identifiers, read off the declared return type** rather
  than off a row. A signature that grew a `payload` column would be a
  cross-tenant disclosure on every claim, and it would pass any test that only
  looks at rows from a queue it seeded itself.
- **The claim takes no tenant argument** — the scheduler does not take
  instructions about whose work to prefer from whoever called it.
- **Fair share is observable.** `test_one_tenants_backlog_does_not_starve_another`
  and `test_a_high_priority_job_does_not_jump_another_tenants_queue`: priority
  orders a tenant's own work and never crosses a tenant boundary.
- **Two sweepers requeue a job once**, and **two concurrent failures do not race
  the attempt counter** — both would otherwise silently spend a tenant's retry
  budget twice.
- **The failure reason is approved copy, not an exception message.**
  `test_the_failure_reason_is_approved_copy_not_an_exception_message` — what
  reaches a tenant's console is `verdict.code` through the copy catalogue;
  `str(exc)` stays in the operator's log with `exc_info` (NR-NF-06).
- **A handler's writes and its success commit together.** `succeed` runs *inside*
  the handler's transaction, so there is no interval in which the effects and the
  record of them disagree. A failed handler's partial writes are rolled back and
  the failure is still recorded, from a transaction opened fresh.
- **A handler sees only its own tenant** — the worker is no more privileged than
  a request handler once the claim has answered.

Each race test was run five times consecutively; all green.

---

## 3. Defects found and fixed

All four were found by tests, and all four are quiet failures — nothing errors,
the queue drains, and the only symptom is wrong behaviour somebody notices weeks
later.

**3.1 A job could be claimed twice.** The `status = 'queued'` predicate lived
only in the claim's subquery. When a locked row is released by a *committing*
holder, PostgreSQL's EvalPlanQual re-reads the new version and re-checks only the
locking query's own level qualification — the stale subquery snapshot still said
"queued", and the row was handed to a second worker. This is precisely the
failure `SKIP LOCKED` exists to prevent, defeated by where the predicate was
written. Fixed by repeating `status` and `run_after` in the outer `WHERE` and
guarding the final `UPDATE`.

**3.2 Fair share starved the wrong tenant.** Ranking only *queued* rows means a
claimed job vacates its rank, so the backlogged tenant is promoted back to rank 1
every round and takes every slot — the exact opposite of the intent. Fixed by
ranking over *live* jobs, queued and running, running first.

**3.3 A worker that had lost its lease reported outcomes it never recorded.**
`JobQueue.fail`'s retryable branches did not inspect `rowcount`. Fixed: both
branches raise `JobLeaseLost` on anything but one row.

**3.4 `JobContext.stage()` never bound its control session.** `SET LOCAL` dies
with its transaction, and `stage()` opens a fresh one — so every progress write
was denied by the tenant's own policy, the guarded `UPDATE` matched nothing, and
the handler was told it had lost a lease it still held. Every job with more than
one stage would have failed, and the message would have blamed the lease. Found
by `test_cancellation_is_observed_at_a_stage_boundary`.

---

## 4. Departures and what was **not** done

**4.1 Handlers.** `apps/job_worker/registry.py` is empty. The queue is complete
and tested; there is no work to run until Phase 6 registers `event_batch` and
`product_bulk_upsert`. The worker refuses to start rather than pretending
otherwise, and the compose service is behind a profile for the same reason.

**4.2 No API surface.** There is no `GET /v1/jobs` or `POST /v1/jobs/{id}:cancel`
yet. `JobQueue.request_cancellation` already raises `ConflictError("job_not_cancellable")`
on a terminal job and `NotFoundError` on another tenant's, so the router is a thin
wrapper — but it belongs with the resources that create jobs (Phase 6) rather
than standing alone here.

**4.3 A stage boundary reports the stage being entered.** `ctx.stage("building_graph")`
raising on a cancellation records `stage_at = "building_graph"`, not the
completed `preparing_data`. Both readings of dc.html L1707 are defensible; this
one is what is implemented, and `test_cancellation_is_observed_at_a_stage_boundary`
states it explicitly so a change is a decision rather than a drift.

**4.4 A handler that declares no boundary cannot be cancelled.** This is a
consequence of cooperative cancellation, not an oversight, and it is written down
as a passing test (`test_a_handler_that_never_reaches_a_boundary_cannot_be_cancelled`)
rather than as a docstring nobody reads.

**4.5 `training` is not claimed by `job_worker`.** It is globally serialised
(ASM-03) and wants a different machine. Phase 8's `training_worker` registers it.

---

## 5. Decisions recorded

**ADR 0011 — PostgreSQL is the broker, and a claim is a `SECURITY DEFINER`
function.** Status: *Accepted — confirmed by instruction to proceed*.

BUILD_PROMPT marks Phase 4 🛑 *"CONFIRM D2 (Postgres queue) before starting"*.
The instruction was "complete phase 4 – 8", with no separate answer to the gate.
Phase 4 was therefore built to BUILD_PROMPT's own recommendation and the ADR
records the confirmation as what it is: weaker than an explicit answer. **This is
a departure from §2** and is named here rather than buried. If the intended
answer was a broker, the seam is `JobQueue` — enqueue/claim/heartbeat/fail — and
the handler contract does not mention PostgreSQL.

ADR 0011 also records the two failure modes in §3.1 and §3.2, because they are
not obvious from reading the SQL and they will be rediscovered by whoever edits
it next.

---

## 6. Open items requiring a human

**6.1 CI has still never executed.** Carried from Phases 1–3. The workflow exists
and every gate in it passes locally.

**6.2 The local Docker stack is not usable as-is.** `graphrec-postgres-1` was
recreated without `POSTGRES_PORT=5442` and now binds host 5432, clashing with the
native PostgreSQL the tests use; the `migrate` image is stale and fails with
"Can't locate revision identified by '0005'". Everything in §2 was verified
against the native instance. The stack needs `POSTGRES_PORT=5442`,
`REDIS_PORT=6389`, `S3_PORT=9010`, `S3_CONSOLE_PORT=9011` recorded in `.env`
and an image rebuild.

**6.3 Unchanged conflicts.** Email delivery (Phase 3 §6.2); the Qdrant conflict
between SRS §6.3 and D4, which needs an explicit "defer Qdrant" decision before
Phase 10.

---

## 7. Phase 5 gate

BUILD_PROMPT marks Phase 5 🛑 *"CONFIRM D9 (write model) and D10 (pagination)"*.
Both are being handled the way D2 was — built to the recommended option (D9:
`POST` + `PUT` + `PATCH`; D10: limit/offset for console lists, cursor for volume
reads), recorded as ADRs marked *confirmed by instruction to proceed*. Both are
substantially cheaper to revisit than D2: D9 adds or removes a verb on one
resource, D10 adds or removes a parameter on a list.

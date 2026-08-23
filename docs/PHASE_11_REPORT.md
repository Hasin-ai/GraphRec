# Phase 11 — Serving

**Scope (BUILD_PROMPT L665-669):** 🛑 D3 closed by ADR 0028 · `model_deployments`,
`deployment_revisions`, `serving_replicas`, `model_activation_history` ·
`ServingDriver` port + Compose adapter · `reconciler` with a leader lock,
desired→actual convergence, replica reporting, `ready ≥ 1` floor · `inference`
pinned by `GRAPHREC_TENANT_ID`, local Ed25519 verification, bundle load with
manifest and digest verification · the four-stage funnel with deterministic
ordering and a versioned policy · fallback lanes · `:activate` and `:rollback`
with load-before-swap and previous-version retention · `POST
/v1/recommendations`, `/session`, `/feedback/*` · `GET /v1/deployment*`,
`/metrics/summary`, `/service-status/errors`.

**Done when:** a failed activation leaves the previous version serving; P95 <
300 ms under load (NR-NF-04); `ready ≥ 1` holds for every active tenant.

**Gate:** D3 was closed by **ADR 0028** — orchestration is Docker Compose behind
a `ServingDriver` port — accepted before any code was written.

## 1. Built

~7,900 lines across schema, the driver port, the domain, two new application
processes, the control-plane router and the tests.

* **`migrations/versions/0012_serving.py`** (787) — eight tables with RLS
  `FORCE` on all of them: `model_deployments`, `deployment_revisions`,
  `serving_replicas`, `model_activation_history`, `recommendation_requests`,
  `recommendation_results`, `recommendation_impressions`,
  `recommendation_feedback`. Four rules the schema holds rather than the
  application: `ck_model_deployments_replica_bounds`,
  `ck_recommendation_requests_identified` (every request is attributable to
  somebody), `ck_recommendation_requests_error_explained` (anything other than
  `served` must say why, and `served` must not invent a reason) and
  `uq_recommendation_impressions_ref` (the retry key). History tables carry
  `SELECT, INSERT` and no `UPDATE` grant.
* **`graphrec/serving_driver/`** (379 + port) — `ServingDriver` with
  `apply`/`observe`/`stop`, an `InProcessDriver` for development and a
  `ComposeDriver` that shells `docker compose` with one file per tenant project.
  `build_serving_driver(K3S)` raises naming ADR 0028.
* **`graphrec/domain/serving/`** (2,375) — `recommend` (the four-stage funnel and
  the fallback lanes), `funnel` (ordering and the versioned policy), `activation`
  (`:activate`, `:rollback`, load-before-swap), `deployment` (desired state),
  `reconciler` (convergence, the leader lock, the `ready ≥ 1` floor), `feedback`
  and `metrics`.
* **`apps/inference/`** (1,076) — the pinned per-tenant process: `binding.py`
  (the bundle binder and its refusals), `deps.py` (gates 1–3 in the credential
  realm only), `schemas.py`, `main.py` (lifespan, the poller, `/healthz`,
  `/readyz`, `/v1/recommendations`, `/v1/recommendations/session`,
  `/v1/feedback/*`).
* **`apps/reconciler/main.py`** (265) — one leader elected by PostgreSQL, a
  serial sweep over tenants using the platform role, per-tenant failure
  isolation and a draining shutdown.
* **`apps/control_api/routers/serving.py`** (350) — `GET /v1/deployment`,
  `/v1/deployment/replicas`, `POST …:activate`, `…:rollback`,
  `GET /v1/metrics/summary`, `GET /v1/service-status/errors`.
* **`deploy/single/docker-compose.serving.yml`** (155) — one template applied
  per tenant as `graphrec-serve-<tenant>`, with a `/readyz`-body healthcheck.
* **`graphrec/http/`** (344) — the error handlers and middleware, extracted from
  `apps/control_api/` so both applications share one envelope without either
  importing the other.
* **`graphrec/serving/states.py`** (183) — backend-only vocabulary:
  `DeploymentState`, `ReplicaState`, `RequestStatus`, `CandidateSource`,
  `ServingErrorClass`, `FeedbackType`.

## 2. Verified

**76 tests in `tests/serving/`.** `ruff format --check` (245 files),
`ruff check`, `mypy graphrec apps` (144 files) and `lint-imports` (3 kept, 0
broken) all clean.

| Module | Tests | What it holds |
| --- | --- | --- |
| `test_driver.py` | 12 | Both adapters against one contract; `_parse_ps` over five real output shapes; a Docker-gated reach to the daemon |
| `test_activation.py` | 6 | ER-F-06, ER-F-07, load-before-swap, previous-version retention |
| `test_reconciler.py` | 7 | Election, lock release, the floor, replica rows, per-tenant failure isolation |
| `test_recommendations.py` | 12 | ER-F-05, ER-NF-06, the lanes, eligibility, exclusions, cross-tenant isolation |
| `test_binding.py` | 8 | What a process agrees to serve, and its four refusals |
| `test_inference_api.py` | 16 | The data plane over HTTP, through the process that serves it |
| `test_metrics.py` | 12 | `delayed`-not-zero, availability, the closed error set |
| `test_load.py` | 2 | NR-NF-04, marked `slow` |

**The exit criteria, each named to a test.**

*"A failed activation leaves the previous version serving"* —
`test_activation.py::test_a_failed_activation_leaves_the_previous_version_serving`,
and at the HTTP boundary by
`test_inference_api.py::test_readyz_stays_unready_when_the_bundle_belongs_to_another_tenant`:
the candidate process starts, never reports ready, and the swap the reconciler
would have made never happens.

*"`ready ≥ 1` holds for every active tenant"* —
`test_reconciler.py::test_the_floor_is_breached_while_coming_up_and_restored_once_ready`.
The floor is a warning with a transient state, not an invariant asserted at
every instant: a replica that is starting has not yet breached anything.

*"P95 < 300 ms under load (NR-NF-04)"* —
`test_load.py::test_the_p95_of_a_recommendation_stays_within_the_budget_under_load`,
200 requests at concurrency 10 through the real ASGI application. Measured
here: **server median 6 ms, server p95 24 ms, server max 62 ms**. The fallback
path is measured separately (`test_a_fallback_answer_is_also_within_the_budget`,
server p95 22 ms), because the lanes are queries rather than a resident matrix
and are therefore the path most likely to miss the budget.

The assertion is made against the **service's own clock** —
`recommendation_requests.latency_ms`, which is what `/v1/metrics/summary`
reports to the tenant — and not against the caller's wall clock, which the same
run records at a p95 of 201 ms. The gap is queueing inside the harness rather
than latency in the service: `httpx.ASGITransport` runs the application in the
same event loop, on the same CPU, as the client generating the load, so ten
in-flight requests are ten coroutines taking turns on one thread. In a
deployment they are spread over `min_replicas` processes. Asserting the
caller's clock would pin a number about Python's scheduler and would go red on
any slower machine, which is the worse failure: an exit criterion that fails for
reasons unrelated to the service stops being read. The wall clock is printed
every run and bounded at three times the budget as a collapse guard.

*"Inference refuses a bundle with a mismatched tenant (plan L1678)"* —
`test_binding.py::test_a_bundle_belonging_to_another_tenant_is_refused`, using a
bundle written by the real `write_bundle` under alpha's key with beta's tenant in
the manifest. Also
`test_a_bundle_naming_a_different_version_is_refused`: the same tenant's bytes
stored under another version's key, which would make ER-F-05's `model_version`
field a lie.

## 3. Decisions and deviations

**The reconciler's sweep uses the platform role.** Enumerating tenants is a
cross-tenant read the tenant role cannot and should not perform. The platform
grant is six columns of `model_deployments` and nothing else — it can see which
deployments exist and what they want, and not one product, event or customer.

**A pinned process still polls.** `GRAPHREC_MODEL_VERSION_ID` fixes the version,
so a poll cannot change it — but the *epoch* moves underneath, and a rollback to
the version already resident is a new epoch on the same id. Without the epoch in
the binding the two would be indistinguishable and a replica would report itself
as serving something nobody currently wants.

**Activation converges asynchronously.** `:activate` writes desired state and
returns; the reconciler performs the swap. A synchronous activation would hold
an HTTP request open for the length of an image pull, and the console's
deployment screen already polls.

**Load-before-swap is a property of the sequence, so the tests use a real
driver.** `InProcessDriver` rather than a mock: a driver whose `observe`
returned whatever a test wanted would be testing the assertion instead of the
sequence `apply → observe → swap`.

**`Settings.compose_file` was renamed `serving_compose_file`.** `COMPOSE_FILE`
is Docker Compose's own reserved variable, and `Settings` has no `env_prefix`.
The reconciler spawns `docker compose` inheriting its environment, so every
invocation would have silently inherited it as the default `-f`.

**The Compose template's `${…:?}` guards were dropped to `${…:-}`.** Compose
interpolates the whole file for every command, including `ps` and `stop`, and
those have no version to supply — the guards made `observe` and `stop` fail.
The guard belongs in the process: `create_app` raises `MissingTenantPinError`
without a tenant pin.

**`create_app_factory = build`** gives the Compose file a stable ASGI entry
point a refactor cannot rename, while `create_app` still raises rather than
exposing a module-level `app` that would make importing the module depend on the
environment being a deployment.

**`RecommendationInput.identity_hash()` was added.** See §4 — the column now
means "the identity this request came from, when it is not a row", hashed
unsalted for the same reason a session id is.

**Metrics are computed from rows, not from a scrape.** A Prometheus that is
unreachable would make availability unmeasurable, and the plan's rule (L1200) is
that a missing measurement is reported as missing. `percentile_cont` over the
window rather than a bucketed approximation: the volumes are one tenant's and an
exact percentile costs a sort nobody will notice.

**`error_class` and `error_reason` live on `recommendation_requests`.** The
error panel is a view over the request log rather than a second store, which is
what makes "a successful request never appears in it" a property of one column
instead of an invariant between two tables.

**`graphrec/http/` was extracted from `apps/control_api/`** against BACKEND_PLAN
§20's tree, and `ForbiddenError` moved to `graphrec.common.errors`. Both
applications raise it, and the import-linter contract forbids either from
importing the other; a second definition would be a second `403` with the same
name and, eventually, different copy.

**`candidate_index` is deliberately not wired into the control API's
`app.state`.** The control plane does not serve recommendations, and an index it
could reach is an index somebody will eventually reach for.

**The mean-of-embeddings query is an approximation.** A session's query vector
is the mean of its recent items' embeddings. A sequence model would use the
order; ADR 0023's pathway does not yet, and the funnel's contract does not
depend on which it is.

## 4. Bugs this phase found in code written earlier

**A cold-start request naming an unknown customer could not be recorded at all**
(`graphrec/domain/serving/recommend.py`). `ck_recommendation_requests_identified`
requires every request to be attributable to somebody. A request naming an
external customer id the platform has never seen resolved `customer=None` and,
with no session, `session_hash=None` — so the row violated the check and the
single most common cold-start case was unwritable. Fixed with
`RecommendationInput.identity_hash()`: when there is no customer row to point
at, the external identifier is hashed into `session_hash`. Found by
`test_recommendations.py`.

**Every duplicate in a feedback batch was reported as an acceptance**
(`graphrec/domain/serving/feedback.py`). `_insert` decided by
`CursorResult.rowcount`, but an ORM insert against an entity with a generated key
already carries an implicit `RETURNING`, and psycopg reports `rowcount` as `-1`
on such a statement until the rows are consumed. `bool(-1)` is `True`, so
`ON CONFLICT DO NOTHING` correctly stored one row while the receipt claimed two.
An integrator asking "did my retry get counted twice?" would have been told yes
when the answer was no. Fixed by asking for the key back and checking whether a
row arrived, which `DO NOTHING` answers unambiguously. Found by
`test_inference_api.py::test_feedback_counts_duplicates_separately_from_acceptances`.
`graphrec/domain/ingestion/merge.py::_affected` was checked and is unaffected —
its statements are `sa.text()` with no `RETURNING`.

**Every authenticated data-plane route answered `422`**
(`apps/inference/deps.py`). `HTTPAuthorizationCredentials` and `Settings` were
imported under `TYPE_CHECKING`, and with `from __future__ import annotations`
FastAPI resolves a dependency's parameter annotations against the module's
globals. A name it cannot resolve does not raise — the parameter silently stops
being a dependency and becomes a **body** field, so every request was refused for
a missing `credentials` field. Invisible to every test that called the domain
directly; caught by the first test that went through HTTP. Both are now runtime
imports with a comment recording why.

**The deployed ingestion worker moved a counter nobody could see**
(`apps/job_worker/main.py`). `Worker` defaults `counters` to
`InMemoryUsageCounters()` so that a unit test needs no Redis, and the shipped
process took that default. Every batch it charged incremented a counter that
died with the process, while `/v1/usage` and every quota check read the shared
Redis one. The ledger — the tenant's bill — stayed correct; the *reported*
usage under-reported every asynchronously ingested batch, and a quota check
kept passing on a stale number until the key expired. Fixed by wiring
`ResilientUsageCounters(RedisUsageCounters(...))` into the worker.

The test that should have caught it was building its own worker the same wrong
way: `tests/ingestion/conftest.py::drain` also took the default, so the API and
the worker disagreed identically in the test and in production and the two
mistakes cancelled. Now it constructs the counters `apps/job_worker/main.py`
constructs. **The suite passed for two phases because Redis was unreachable** —
with no cache, `counters.current` repairs from the ledger on every read and the
right answer comes back slowly. Found while setting `REDIS_URL` for this
phase's load test.

**The Compose template's required-variable guards broke two of the driver's
three operations.** Caught because the driver-contract test actually reaches the
daemon rather than asserting against a fake. See §3.

**Usage counters outlived the ledger they mirror.** Every fixture that empties
`usage_events` puts a tenant back at the start of their month in the database
and left the Redis mirror of that month saying what it said before. `current`
only recomputes on a *miss*, so a hit on a stale key is authoritative: with
Redis reachable, nine `tests/training/test_training_api.py` tests were told
their quota was exhausted by usage no table recorded. The counter behaved
exactly as designed — stale-high is the direction metering deliberately errs in
— so the fix belongs to the teardown, and is a `usage:*` sweep in
`tests/conftest.py::_sweep_counters`. Scanned rather than flushed: `usage:` is
the whole prefix metering owns, and `FLUSHDB` on a developer's Redis would take
their sessions and queues with it. Confirmed pre-existing at `HEAD` with
`git stash`; it was invisible for the same reason the counter bug above was, and
was uncovered by the same fix.

**Neither app disconnected its Redis pool at shutdown.** `apps/control_api` and
`apps/inference` both called `redis.aclose()` in their lifespan, which returns
the client's own connection and leaves every other connection in the pool open.
`apps/job_worker` had it too. A process that starts and stops an app — a test, a
reload, a one-off command — therefore left sockets for the garbage collector to
notice later as an unraisable `ResourceWarning`, which this suite promotes to an
error and which surfaced as failures attributed to whichever test happened to be
running when the collector ran. All three now hold the pool and `disconnect()`
it. Also pre-existing, and also masked by Redis being unreachable: an app that
never connects has no sockets to leak.

## 5. Not done

**No circuit breaker on the usage cache.** With Redis unreachable, every request
pays a connection attempt before `ResilientUsageCounters` falls back to the
ledger. Correctness is unaffected — a quota check never passes because a cache is
down — but the latency is: the same load test pointed at an unreachable Redis
measures a server p95 of 30 ms against 24 ms with a warm cache, so the cost is
real and small at this volume. A short-lived breaker that skips the cache for a
few seconds after a failure would recover it. Deferred rather than done because
the budget holds comfortably either way.

**Ed25519 verification is local only.** The inference process verifies the
bundle's manifest and digest. There is no signing authority beyond the training
process that wrote it, so a compromised training process could produce a bundle
that verifies.

**The reconciler is serial.** One tenant at a time, ordered by `tenant_id`. A
tenant whose image pull is slow delays the sweep for everyone behind it. At the
scale ADR 0028 is scoped for this is the right trade — parallelism here means
concurrent `docker compose` invocations against one daemon.

**No sticky routing.** A tenant's replicas are interchangeable and Compose
round-robins between them, so two requests in one session may be answered by
different replicas at different epochs during an activation. Both answers are
valid; they may name different `model_version` values.

**`serving_replicas` rows are not swept.** A replica that vanishes without the
reconciler observing it leaves a row until the next successful `observe` for
that tenant.

**The training worker still takes the in-memory counter default.** Nothing in
its registry meters today, so the defect above cannot occur there — but the
trap is the same one, and the next handler that charges will fall into it.

**Still open from earlier phases:** the 15-minute training cooldown is
provisional; there is no retention sweep for orphaned artifacts; training
concurrency is per tenant rather than platform-wide; the metric floor is not
tenant-configurable.

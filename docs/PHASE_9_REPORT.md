# Phase 9 — Training jobs

**Scope (BUILD_PROMPT L657):** `models`, `training_jobs`, `dataset_snapshots`,
`training_metrics` · the partial unique index for one active job per tenant ·
`training_worker` implementing the nine stages, writing `progress` and
`stage_index` at each · `POST /v1/training-jobs` with all four admission checks
at enqueue · `GET /v1/training-jobs/eligibility` · `GET /v1/training-jobs/{id}`
with the stage-rail contract · `:cancel` with a required reason ·
`GET /v1/datasets/snapshots/{id}`.

**Gate:** none. The next gate is D4/D8 before Phase 10.

Phase 8's loop is unchanged. Nothing under `graphrec/ml/` acquired a session, a
tenant or a bucket in this phase, which was the property Phase 9 was asked to
preserve; the wiring lives entirely in `graphrec/domain/training/`.

## 1. Built

~5,700 lines across schema, storage, domain, worker, API and tests.

* **`migrations/versions/0010_training.py`** (478) — four tables, RLS with
  `FORCE` on all of them, and the two indices that carry the phase's rules:
  `uq_training_jobs_one_active` partial on `tenant_id` over the nine
  non-terminal states, and `uq_training_jobs_request_ref` on
  `(tenant_id, request_ref)`. `dataset_snapshots` and `training_metrics` are
  append-only by absent grant, not by trigger. Three check constraints tie the
  terminal columns to the state: `ck_training_jobs_terminal_dated`,
  `ck_training_jobs_cancel_reason`, `ck_training_jobs_failure_reason`.
* **`graphrec/training/states.py`** (90) — `STAGE_NAMES`, `STAGE_RAIL`,
  `ACTIVE_STATES`, `TERMINAL_STATES`, `stage_index`. A top-level package rather
  than a module under `domain/`, so `db` can import the state vocabulary without
  the `db → domain` cycle.
* **`graphrec/storage/`** (384) — the `ArtifactStore` port, an S3 adapter, a
  local adapter, `keys.py` (every key prefixed `tenants/{tenant_id}/`, escape
  refused), and `factory.py` selecting between them from `Settings`. Digests are
  computed on write and verified on read.
* **`graphrec/domain/training/snapshot.py`** (323) — the frozen window: `.npz`
  with a JSON header, `allow_pickle` left at `False`, and
  `count_eligible_sequences` shared by the eligibility card and the admission
  check so the two cannot disagree.
* **`graphrec/domain/training/eligibility.py`** (327) — the four checks in one
  place, evaluated once and used twice: rendered by `GET /eligibility` and
  raised by `POST`. Order is fixed — active run, cooldown, quota, data.
* **`graphrec/domain/training/service.py`** (585) — admission, replay,
  cancellation, and the reads behind the five routes. `render_stage_rail`
  reproduces the prototype's branch table at L1707 server-side.
* **`graphrec/domain/training/pipeline.py`** (798) — the nine stages, the `Rail`
  that publishes them, checkpoint resume, per-epoch metrics, embedding export.
  Training runs through `anyio.to_thread`; `on_epoch` and `should_stop` are
  bridged back to the loop with `anyio.from_thread`.
* **`apps/training_worker/`** (105) — the same `Worker` as `job_worker`, with a
  registry holding one handler and `WORKER_CONCURRENCY: 1`. A `training_worker`
  service was added to `docker-compose.yml` under the `workers` profile with a
  600-second `stop_grace_period`.
* **`apps/control_api/routers/training.py`** (323) — the seven routes, session
  realm only.

## 2. Verified

* `ruff format --check` (198 files), `ruff check`, `mypy graphrec apps`
  (115 source files) and `lint-imports` (3/3 contracts) all clean.
* **837 tests pass** against a live PostgreSQL with `GRAPHREC_REQUIRE_DB=1`,
  twice in succession. 61 are new: 52 in `tests/training/`, 8 in
  `tests/storage/`, 1 added to the migration-literal contract.

The three exit criteria, each pinned by a named test:

* **Two concurrent requests yield one job and one `409`** —
  `test_two_concurrent_requests_yield_one_job_and_one_conflict` opens two
  connections and drives both inserts into the partial unique index. Also at the
  HTTP surface: `test_a_second_run_while_one_is_active_is_a_409`.
* **A crash mid-training resumes from the last checkpoint** —
  `test_a_crash_mid_training_resumes_from_the_last_checkpoint` kills the run
  inside `training` after three checkpointed epochs, lets the queue hand the same
  job back, and asserts the resumed attempt trains past the crash without
  re-recording epoch 1.
* **`stage_index` survives failure and cancellation** —
  `test_cancelling_mid_run_records_the_stage_it_stopped_at` (index 3, "stopped
  at building_graph") and `test_a_run_below_the_minimum_fails_permanently_and_
  keeps_its_position`.

## 3. Decisions and deviations

* **`training_jobs.snapshot_id` and `.model_version_id` are not stored.** The
  plan lists them alongside `dataset_snapshots.training_job_id UNIQUE` and
  `model_versions.training_job_id`; that is the same edge twice, and a pair of
  columns that can disagree eventually does. The unique back-references are kept
  and the forward copies dropped. Recorded in the migration's docstring.
* **Concurrency is enforced per tenant, not platform-wide.** The console says
  *"Global training concurrency is 1"* (L1646) and ASM-03 says the same. The
  partial unique index is per tenant, which is the weaker rule: four tenants can
  each hold one run. This is deliberate for now — a genuinely global
  serialisation belongs with the reconciler's leader lock in Phase 11 — and it
  is flagged in `eligibility.CONCURRENCY_SCOPE` and in the compose comment
  rather than left to be discovered.
* **A retryable crash does not write `failed`.** The rail is left exactly where
  it stopped and only the attempt that finds no retry left records a terminal
  failure. Writing `failed` on every crash would put a terminal state on a run
  that is about to resume, and the console would show a failure that un-fails
  itself. The cost is that a run between attempts reads as still being in its
  last stage, which is what it is.
* **A retry adopts the first attempt's snapshot rather than freezing a new
  window.** `UNIQUE(training_job_id)` requires it and correctness wants it: the
  checkpoint being resumed was trained against that cut-off, and reading a
  fresher window would invalidate the epochs already spent.
* **The handler holds `ctx.session`'s transaction open for the length of the
  run.** Every durable write — the rail, the snapshot row, the metrics — goes
  through `ctx.control()` on the second connection instead, so a run that fails
  after six epochs still leaves six epochs of curve behind.
* **A run cancelled before any worker claimed it is settled by the API.**
  `JobQueue.finish_cancelled` requires the lease, correctly: only the process
  doing the work can say where it stopped. A queued job has no such process, so
  `JobQueue.cancel_unclaimed` settles it under a `status = 'queued'` guard. One
  window is left open: a worker that dies holding the lease leaves the row
  `running`, and a cancellation arriving before the sweeper requeues it is
  recorded but not settled until the next claim observes it.

## 4. Bugs this phase found in code written earlier

* **`_translate` rolled back a transaction it did not own.** Translating the
  unique violation into a `409` called `session.rollback()` inside the router's
  `session.begin()`, which raises `InvalidRequestError` — the second of two
  concurrent requests would have received a `500` rather than the `409` the exit
  criterion asks for. Enqueue and insert now happen inside a SAVEPOINT.
* **Two first-ever concurrent requests collided on the wrong index.** Both
  inserted the tenant's lazily-created `default` model and lost to
  `uq_models_tenant_name` instead of to `uq_training_jobs_one_active`, producing
  a unique violation on a container nobody asked for. The insert is now
  `ON CONFLICT DO NOTHING` followed by a re-select.
* **`Eligibility.reason` read a method as an attribute.** `GraphRecError.reason`
  resolves copy on call; `getattr(blocker, "reason", None)` returned the bound
  method, and `str()` of it — `"<bound method GraphRecError.reason of …>"` —
  would have been rendered at the tenant in the eligibility tooltip. Neither
  mypy nor ruff objects to it, because it is well-typed nonsense. Found by
  `test_eligibility_names_the_run_in_the_way`, which asserts the job identifier
  appears in the sentence.
* **`CURVE_METRICS` held literal cut-off suffixes.** `Metrics.as_dict` suffixes
  three of five names with K, so at K=5 only `coverage` was stored and the
  curve was silently almost empty. Now matched by family with an anchored
  regex.
* **A run cancelled while queued sat at `cancelling` for ever.** The worker
  raises `JobCancelled(None)` before invoking the handler, so nothing ever moved
  the training row. See §3.

## 5. Not done

* **No model version, no bundle, no registry.** `indexing_embeddings` exports
  the item matrix as safetensors with a manifest carrying `tenant_id` and the
  training job id, and stops there. Registration, the metric floor and the
  `CandidateIndex` port are Phase 10.
* **The metric floor is not written.** ADR 0024's caution stands: a floor
  imported from published sampled-negative figures would be roughly three times
  too high. Phase 10 must calibrate against numbers produced by the
  full-catalogue protocol.
* **The 15-minute cooldown is still provisional.** It appears on a stat card in
  the prototype and nowhere in the SRS (BACKEND_PLAN §7.3), so it is a setting
  that can be turned to zero rather than a rule in the schema.
* **No retention sweep for orphaned artifacts.** A crash between the object
  write and the row insert leaves a snapshot in the store with no row pointing at
  it. Harmless and invisible; it needs the retention job, which is not this
  phase.
* **The SRS §6.3 Qdrant vs D4 conflict is still open.** It has to be settled by
  an explicit ADR before Phase 10 builds the in-process index, rather than by
  building the index and letting the SRS quietly become wrong.

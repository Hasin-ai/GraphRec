# Phase 10 — Model registry

**Scope (BUILD_PROMPT L660-663):** 🛑 CONFIRM D4 (in-process index) and D8
(7-value lifecycle) before starting · `model_versions`,
`model_evaluation_metrics` · partial unique for one active version · bundle
export in safetensors with a manifest carrying `tenant_id` and a digest ·
`CandidateIndex` port + in-process adapter, built and uploaded by the
`indexing_embeddings` stage · registration sets `registered`, then `eligible` or
`rejected` against the metric floor · `GET /v1/model-versions`, `/summary`,
`/{id}` with the three-way comparison and the `actions` block · `:archive` with
rollback-target protection.
**Done when:** a corrupted bundle is refused at load and a foreign-tenant
manifest is refused.

**Gates:** D4 and D8, both confirmed by instruction to proceed and recorded as
ADR 0026 and ADR 0027 before any code was written.

## 1. Built

~3,850 lines across schema, artifacts, domain, API and tests.

* **`migrations/versions/0011_registry.py`** (306) — two tables, RLS `FORCE` on
  both. Three rules the schema holds rather than the application:
  `uq_model_versions_one_active` (partial unique on `tenant_id WHERE status =
  'active'`), `ck_model_versions_archived_dated` (`(status='archived') =
  (archived_at IS NOT NULL)`), and `ck_model_versions_failure_note` (a note only
  on `rejected`, `failed_deployment`, `archived`). Immutability is the absence
  of a grant, as everywhere else: `model_versions` gets `SELECT, INSERT, UPDATE
  (status, failure_note, archived_at)` and `model_evaluation_metrics` gets
  `SELECT, INSERT`. `training_job_id` and `snapshot_id` are `RESTRICT`, not
  `CASCADE` — deleting a run must not silently delete the record of an artifact
  a tenant may be serving from.
* **`graphrec/ml/bundle.py`** (385) — a single-file safetensors bundle with the
  manifest in the header. `write_bundle` is atomic (`mkstemp` + `os.replace`);
  `load_bundle` verifies, in this order: parses as safetensors, has a manifest,
  format version, **tenant**, has the tensor, shape matches the manifest,
  payload digest matches.
* **`graphrec/ml/index.py`** (258) — the `CandidateIndex` port, the
  `InProcessIndex` adapter (exact top-K, deterministic ties, keyed by
  `(tenant_id, model_version_id)`), and `build_candidate_index`, the selector
  that refuses `candidate_index=qdrant` at startup.
* **`graphrec/db/models/registry.py`** (134) — `ModelVersion` and
  `ModelEvaluationMetric`, with the lifecycle predicates (`is_active`,
  `is_eligible`, `archivable_status`) on the model rather than in four callers.
* **`graphrec/domain/registry/lifecycle.py`** (264) — the metric floor
  (`judge`) and the three gate-5 predicates (`can_activate`, `can_rollback`,
  `can_archive`). Every refusal carries an `Action.code`, which is what the
  endpoint raises.
* **`graphrec/domain/registry/registration.py`** (251) — `register`, in two
  steps: the row as `registered`, then the verdict under a `status =
  'registered'` guard.
* **`graphrec/domain/registry/service.py`** (400) — the list, the five stat
  cards in one `GROUP BY`, the detail page with the three-way comparison, and
  `archive`.
* **`apps/control_api/routers/registry.py`** (195) + schemas — the four routes.
* **`graphrec/domain/training/pipeline.py`** — `indexing_embeddings` now builds
  and uploads a bundle keyed by the version; `registering` writes the row and
  the verdict.
* **ADR 0026** (in-process index, Qdrant deferred behind the port) and
  **ADR 0027** (the seven-state lifecycle), both marked *confirmed by
  instruction to proceed*.

## 2. Verified

77 tests in `tests/registry/`, plus four rewritten and added in
`tests/training/test_pipeline.py`. Full suite: **922 passed**. `ruff format
--check`, `ruff check`, `mypy graphrec apps` (124 files), `lint-imports`
(3 kept, 0 broken) all clean.

**The exit criteria, each named to a test.**

*"A corrupted bundle is refused at load"* —
`tests/registry/test_bundle.py`, in five distinct corruption shapes, because
"corrupted" is not one failure:

| Shape | Test |
| --- | --- |
| Truncated file | `test_a_truncated_bundle_is_refused_at_load` |
| Not safetensors at all | `test_a_file_that_is_not_safetensors_at_all_is_refused` |
| Weights swapped, header intact | `test_swapped_weights_under_an_intact_header_are_refused` |
| Manifest shape lies about the tensor | `test_a_manifest_promising_a_shape_the_tensor_does_not_have_is_refused` |
| No manifest / a future format version | `test_a_bundle_without_a_manifest_is_refused`, `test_a_bundle_from_a_future_format_is_refused_rather_than_partly_read` |

The third is the one that justifies carrying two digests.
`model_versions.artifact_digest` covers the whole file and catches truncation
and substitution in the store; `BundleManifest.payload_digest` covers the tensor
bytes plus the item labels and catches a rewrite that kept the header. The first
cannot see the third row of that table.

*"A foreign-tenant manifest is refused"* —
`test_a_foreign_tenant_manifest_is_refused_at_load`, and, over a bundle a
real pipeline produced rather than one the test wrote,
`tests/training/test_pipeline.py::test_another_tenant_cannot_load_the_bundle_this_run_produced`.
`test_the_refusal_for_a_foreign_bundle_names_no_identifiers` pins that the message
discloses nothing.

**BACKEND_PLAN L1868's six, in order.** Bundle export and digest verification —
`test_a_bundle_round_trips_its_matrix_and_its_labels`, `test_the_payload_digest_covers_the_labels_and_not_only_the_matrix`.
Corrupt bundle detected at load — the table above. Manifest `tenant_id` mismatch
refused — above. Version numbering monotonic per tenant —
`uq_model_versions_number` plus
`test_a_completed_run_registers_a_version_against_the_floor` (version 1 for a
tenant's first run) and `test_a_resumed_run_registers_one_version_rather_than_two`.
Archive protection for the retained rollback target —
`test_the_retained_rollback_target_cannot_be_archived` over HTTP and
`test_the_retired_version_immediately_before_the_active_one_is_protected` as a
unit. Baseline comparison populated —
`test_registration_records_both_the_version_and_the_baseline_it_beat` and
`test_the_detail_compares_the_version_against_the_baseline`.

**Gate 4** — `test_another_tenants_version_is_a_404_and_not_a_403`,
`test_a_version_that_never_existed_is_the_same_404` (the two must be
indistinguishable, or the difference is the oracle),
`test_the_list_shows_nothing_of_another_tenants_registry`, and
`test_archiving_another_tenants_version_is_a_404` on the write path, where
getting it wrong deletes rather than discloses.

**Gate 5** — `test_archiving_the_active_version_is_a_409_with_the_buttons_sentence`
asserts the *same string* in the disabled button's `reason` and in the `409`'s
`error.reason`, read from one `can_archive` call in each place. Not two strings
that look alike.

**§6.3's isolation contract, honoured by the in-process adapter** —
`test_one_tenants_search_cannot_reach_another_tenants_index` and
`test_two_versions_of_one_tenant_are_both_resident_during_an_activation`. The SRS mandates a `tenant_id`
payload filter because a shared collection can be queried without one;
`InProcessIndex` keys on `(tenant_id, model_version_id)`, so there is no shared
collection to forget to filter.

## 3. Decisions and deviations

**The path is a claim; the manifest is evidence.** `keys.belongs_to` checks a
path built by whoever wrote the object. The manifest's `tenant_id` was sealed by
the training process that produced the matrix, so that is what `load_bundle`
checks, and it checks it *before* the shape — another tenant's bundle is a
security failure and a malformed one is an operational failure, and the first
should not be reported as the second.

**Registration is two steps on purpose.** The row is what the run produced; the
status is what the floor decided. A crash between them leaves a state the schema
can hold (`registered`, no note), and `_apply_verdict`'s `status = 'registered'`
guard makes the retry safe — it will not reset a version that has since been
activated or archived.

**The floor is relative first, absolute second.** `judge` tests `value <
baseline * 1.05` before `value < 0.01`, because "lost to popularity" is a
statement about the model and "missed an absolute number" is a statement about
the catalogue, and only the first tells a tenant what to do next. The absolute
minimum is deliberately low: ADR 0024 ranks the whole catalogue, which produces
numbers roughly three times lower than the sampled-negative figures published
for DGSR, and a floor imported from a paper would reject every version this
system will ever train.

**The rollback-target rule is `active_number - version_number <= 1`**, taken
verbatim from the prototype (dc.html L1748-1749). Read as an inequality it also
protects a retired version numbered *above* the active one. That is not an
off-by-one in the prototype: such a version is one that was rolled back *from*,
and it is exactly as much a rollback target as the one below. Pinned by
`test_a_retired_version_numbered_above_the_active_one_is_also_protected`.

**The rollback-target protection is in the service, not in a constraint.** "The
retired version immediately preceding the active one" is a question about
another row, and a check constraint cannot see one. A test stands in for the
constraint that cannot exist — which is the honest arrangement, since it puts
the rule somewhere it can be read.

**Only two new error-copy entries.** The catalogue already carried
`version_already_active`, `version_not_eligible`, `rollback_requires_target`,
`rollback_no_target`, `archive_active_version`, `archive_already_archived` and
`archive_rollback_target`, all pinned byte-for-byte against the prototype. Added
were `model_version_below_baseline` and `model_version_below_minimum`, which are
derived sentences carrying numbers and have no prototype line to match.

**ADR 0026 consequence 3 was rewritten this phase.** As accepted it claimed
"`QDRANT_*` settings are not added to `Settings`", which was false the moment it
was written: `qdrant_url`, `qdrant_collection_prefix`, `qdrant_embedding_dim`
and `qdrant_top_k` were already in `graphrec/common/config.py` and
`.env.example`, and BACKEND_PLAN L467 says to keep them. The consequence now
says what is actually true and what actually protects the operator: the keys are
the deferred adapter's configuration surface, nothing reads them, and
`build_candidate_index` raises `NotImplementedError` naming the ADR rather than
falling back to the matrix. An operator who asked for a real vector store gets a
process that does not come up, not one that comes up serving from something
else.

**`ArchiveVersionRequest.reason` is optional.** The prototype's archive dialog
(L1798) has no reason field. The parameter exists because Phase 12 writes
archive to `audit_logs` and an operator who has a reason should be able to
record it; requiring one would be inventing a control the design does not have.

## 4. Bugs this phase found in code written earlier

**The metric floor did not follow `k`** (`graphrec/domain/training/pipeline.py`).
`MetricFloor` defaults to `recall_at_10` because that is what the console leads
with, but the evaluator emits `recall_at_{k}` and `TrainingPipeline` takes `k`
as a constructor argument. A pipeline built at `k=5` therefore measured
`recall_at_5`, was judged on `recall_at_10`, found no measurement, and rejected
every version — correctly by the letter of `judge`'s missing-measure rule and
wrongly by every other standard. Found by
`test_registration_records_both_the_version_and_the_baseline_it_beat`, which is
run at `k=5`. Fixed by defaulting the floor to `recall_at_{k}`; an explicit
`floor=` still wins, because a caller who names a metric has said which one they
mean.

**`tests/training/conftest.py::_empty_training` did not wipe the registry.** A
completed run now writes a `model_versions` row holding a `RESTRICT` reference
to `training_jobs`. Leaving the two registry tables out of the teardown did not
merely leave the registry dirty — it made training's own teardown fail with a
foreign-key error, in whichever test happened to be next. The two tables now
lead that tuple.

**`ConflictError(..., reason_override=...)` does not exist.** The constructor
parameter is `reason=`. Rather than pass a sentence, `lifecycle.Action` now
carries the `code`, and the service raises `ConflictError(decision.code)` — so
the disabled button's reason and the `409`'s reason resolve from one catalogue
entry by construction rather than by review.

## 5. Not done

* **`:activate` and `:rollback` are Phase 11.** Their *preconditions* are
  already on the wire in the `actions` block, because the console disables those
  buttons before either route exists and a button whose reason arrives a phase
  later is a button with no reason at all.
* **No retention sweep for orphaned artifacts.** `archive` deletes the bundle
  before updating the row, which can leave an orphaned object if the update
  fails; so can a bundle uploaded by a run that crashed before registration. The
  other order would leave a row claiming the artifact is gone beside an artifact
  that is not, which a tenant *can* see. This is the same gap Phase 9 recorded,
  now one object wider.
* **`archive` is a no-op on bytes in a control-plane process without a store.**
  It updates the row and logs; the artifact is left to the sweep above. This is
  the read-only deployment doing the part of the work it can do, not a silent
  failure — but it is a gap until the sweep exists.
* **The Qdrant adapter.** Deferred by ADR 0026, refused loudly rather than
  faked. The port, the isolation tests and the exact-top-K oracle they compare
  against are all in place, so the work is one adapter.
* **The metric floor is not tenant-configurable.** `MetricFloor` is a
  constructor argument with no settings key and no per-tenant override. ADR 0024
  says it must be calibrated; calibrating it needs real catalogues, which the
  platform does not have yet.

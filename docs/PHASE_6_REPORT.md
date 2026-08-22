# Phase 6 — Ingestion

**Scope (BUILD_PROMPT L643-645):** `customers`, `interaction_events`,
`submissions`, `submission_errors`; `POST /v1/events` with
`duplicate_confirmed`; `POST /v1/events/batches` and
`POST /v1/products:bulk-upsert` → `202` + submission + job; worker handlers with
streaming, bounded-memory validation, staging then a single merge transaction
and capped error samples; a unified `GET /v1/submissions/{id}` plus the
`/events/batches/{id}` alias.

**Gate:** none. BUILD_PROMPT marks no 🛑 on ingestion. The next gate is D4/D8
before Phase 10.

## 1. Built

* **Request surface** — `apps/control_api/routers/ingestion.py`, five routes,
  no router prefix (FastAPI asserts a path starts with `/`, so
  `/products:bulk-upsert` cannot live under a `/products` prefix):
  `POST /v1/events` (200), `POST /v1/events/batches` (202/200),
  `POST /v1/products:bulk-upsert` (202/200),
  `GET /v1/submissions/{submission_id}`, `GET /v1/events/batches/{batch_id}`.
* **Dual-realm gate** — `require_ingest()` in `apps/control_api/deps.py`, plus
  `IngestPrincipal`. Session or credential, dispatched on the `gr_live_` prefix,
  judged by role or by scope respectively (ADR 0015).
* **Worker half** — `graphrec/domain/ingestion/processor.py`: two transactions,
  500-item windows over `raw_payload`, staging, one merge, capped samples,
  product-quota check before a catalogue merge (ADR 0014).
* **Registry** — `apps/job_worker/registry.py` now registers
  `JobType.EVENT_BATCH` and `JobType.PRODUCT_BULK_UPSERT` against the real
  handlers, so the tests exercise the process that ships.
* **Wire models** — `apps/control_api/schemas.py`: permissive about content,
  strict about shape, so the domain validator (not Pydantic) produces the
  prototype's sentences.
* **Copy** — two new `ITEM_ERROR_COPY` entries splitting a shape verdict from a
  catalogue verdict (ADR 0018).

## 2. Verified

* `ruff format`, `ruff check` and `mypy graphrec apps` (71 source files) clean.
* **530 tests pass** against a real PostgreSQL 18, with `GRAPHREC_REQUIRE_DB=1`
  so a skipped database test is a failure. 68 of those are new in
  `tests/ingestion/` (validation, bounds, pipeline) plus 27 in
  `test_ingest_api.py`.
* **The exit criteria, each as a named test:**
  * `test_the_same_event_id_twice_yields_one_row_and_two_successes`
  * `test_an_oversize_batch_returns_413` / `test_an_oversize_sync_returns_413`
  * `test_a_partial_failure_keeps_the_accepted_remainder`
* Also held: counts partition (`received = accepted + updated + skipped +
  failed`), error cap at 100 samples with an exact `failed_count` of 400,
  `raw_payload` cleared on completion, staging emptied, cross-tenant read is a
  404 that does not say "submission", per-tenant identifier namespaces, and
  `UPDATE`/`DELETE` on `interaction_events` denied at the role level.

## 3. Defects found and fixed

* `normalise_event` reported a *missing* product identifier as
  `item_unknown_product`, mis-routing the single-event form's field error to a
  catalogue problem. Split into three codes (ADR 0018). Found by a test.
* `Settings` and `uuid` were imported under `TYPE_CHECKING` in `deps.py` and
  `routers/ingestion.py`. With `from __future__ import annotations`, FastAPI
  could not resolve them: the `settings` dependency was demoted to a required
  **query parameter** (every ingest route answered 422 before gate 1 could
  answer 401), and the `submission_id` path parameter raised `PydanticUserError`
  → 500. Both are now runtime imports; `TCH00*` is already ignored for these
  files for exactly this reason.

## 4. Decisions recorded

| ADR | Decision |
| --- | --- |
| 0014 | A submission is written by two transactions; only the handler's may count. |
| 0015 | The ingest realm is decided by the credential presented, never by the caller. |
| 0016 | A repeated collection answers 200; only a new one answers 202. |
| 0017 | `status` (badge) and `stage` (rail) are two vocabularies. |
| 0018 | A missing product identifier is not an unknown product. |

## 5. Not done

* **Optimistic concurrency on products is still unresolved.**
  `product_concurrent_change` (dc.html L1335) is approved copy with **no
  mechanism**. Phase 5's report deferred "where the version travels" into Phase
  6's scope; Phase 6 did not introduce a version token and does not raise the
  code. This is now carried forward twice and should be settled rather than
  deferred again.
* **CI has still never executed.** The workflow exists; no run has happened.
* **Docker stack unverified this session** — the daemon is not running. The
  database work was done against a native Homebrew PostgreSQL 18 at
  `localhost:5432`, so the schema and the role privileges are verified for real,
  but the Compose topology is not re-verified since Phase 3.
* **Qdrant (SRS §6.3) vs D4** still needs an explicit "defer" before Phase 10.
* **Retention and tenant deletion** semantics remain unanswered; `deleted_at` on
  `products` and the cleared `raw_payload` both anticipate a policy that does not
  exist yet.

## 6. New conflicts

None. The prototype, the SRS and BACKEND_PLAN agree on the ingest surface, and
the one place BUILD_PROMPT's "single merge transaction" appeared to conflict with
Phase 4's one-transaction-per-handler rule was resolved in favour of both
(ADR 0014) rather than by weakening either.

# GraphRec SRS implementation report

> **Historical record.** This report describes the state after migration `0026`.
> Since then the TypeScript SDK was removed (`f77184b`; the Python SDK is the
> only client), the production API image no longer contains tests (run them with
> `docker compose --profile test run --rm api-test`), and abrupt worker
> termination is tested with a real process kill. For the current state see
> `docs/GAP_ANALYSIS.md`, `docs/DECISIONS.md` and `CHANGELOG.md`.

Requirements source: `docs/Complete_SRS.pdf` and the user's implementation brief. The PDF's diagrams, use cases, logical model and AI pipeline are product requirements, not instructions to the coding agent. The companion [implementation matrix](srs-implementation-matrix.md) traces UC-01–31. This report records executable behavior, tests, and remaining differences without claiming complete SRS parity.

## 1. Repository analysis

The tenant console is React 19, TypeScript, React Router 7 and Vite in `web`. Its central HTTP client and wire types are `src/api/index.ts` and `src/api/types.ts`; session hooks and route guards limit visible actions by server scopes. `apps/demo-storefront` is a separate tenant application that calls GraphRec through the Python SDK. Shoppers do not authenticate to the administration console.

FastAPI in `apps/api` exposes `/v1` routes. Domain logic lives in `graphrec_core`; SQLAlchemy 2 uses PostgreSQL 17, and Alembic migrations `0001`–`0026` own schema changes. JWT/API-key principals derive tenant identity, and PostgreSQL RLS plus application predicates restrict tenant data. Platform operators use a separate credential. API errors carry a correlation ID in one envelope.

Training jobs are durable PostgreSQL records. A separate single-capacity `graphrec_core.dgsr.worker` process claims queued jobs, trains bounded DGSR, records real stages, persists a local artifact, and indexes learned normalized item embeddings in Qdrant. The API serves synchronously from the active version with catalog eligibility checks and a tenant-popular fallback. Compose runs PostgreSQL, Qdrant, migration, API, worker and frontend. It does not include Celery, RabbitMQ, Redis, RustFS, Kubernetes or tenant-pinned inference pods.

The cross-layer map is: console/storefront → typed client or SDK → `/v1` router → domain service → tenant-scoped PostgreSQL entity; training continues through the worker and Qdrant, while recommendation retrieval reads Qdrant and the active artifact. The matrix names the route, screen, entity and test for each use case.

## 2. Original gaps and changes by diagram

| Diagram | Original gap | Implemented here | Remaining |
| --- | --- | --- | --- |
| L1.1 identity | Active-account recovery was operator-contact guidance only. | Operator issues a single-use recovery token; public redemption validates proof, changes password, revokes refresh sessions and invalidates prior JWTs through `auth_epoch`. UI and SDKs support the flow. | Delivery is operator-assisted; no mail service is configured. |
| L1.2 catalog/events | Bulk sync and event batches had no durable request replay or later per-item outcome history. | Bounded 1000-item submissions, stored request hashes/outcomes, tenant-scoped sync history/detail and event-batch detail, with console and SDK access. | Processing is synchronous; a queue is unnecessary for the bounded request size. |
| L1.3 training | The console searched a list for job detail; cooldown was absent. | Tenant-owned single-job read, polling, serialized training acceptance and cooldown. | Load and abrupt worker-recovery objectives have not been certified. |
| L1.4 models | Desired/active deployment state was implicit; Qdrant readiness was not checked before activation; rollback protection was incomplete. | Persisted deployment attempts, Qdrant readiness checks, last-known-good preservation and protected rollback target. | No tenant-pinned inference replica or fresh common-dataset version comparison. |
| L1.5 serving | Request context/fallback permission and normalized ranked results were missing. | Validate shopper/session context, enforce fallback opt-out, store ranked tenant/product result rows, register tenant-owned shopper identities, and link click/conversion feedback to ranked rows. | No typed hints, Redis/item-neighbor tiers or learned reranker. |
| L1.6 usage/admin | Operators lacked tenant usage read and editable plans; status lacked persisted deployment counts. | Aggregate operator usage, audited bounded plan editing, and desired/active/ready deployment status in tenant and platform screens. | Per-tenant capacity scaling and exhaustive infrastructure-failure capture remain unverified. |

## 3. Changed-file inventory

Each path below identifies a changed file and its purpose. Related paths share a row when they implement one contract.

| File(s) | Purpose |
| --- | --- |
| `.env.example`, `docker-compose.yml`, `graphrec_core/settings.py` | Configure and pass the training cooldown to API and worker. |
| `web/nginx.conf` | Resolve the API address through Docker DNS when containers are recreated. |
| `web/e2e/console.spec.ts`, `e2e/lifecycle.spec.ts`, `e2e/roles.spec.ts` | Assert current deployment wording and rollback protection; honor registration retry timing in repeated runs. |
| `.gitignore` | Track the two SRS deliverables while ignoring other generated docs. |
| `docs/srs-implementation-matrix.md`, `docs/srs-implementation-report.md` | Record traceability, architecture, evidence and limits. |
| `migrations/versions/0020_platform_plan_edit.py` | Allow bounded operator plan updates. |
| `migrations/versions/0021_account_recovery.py` | Recovery proof storage/RLS, user auth epoch and refresh-session revocation support. |
| `migrations/versions/0022_durable_ingestion.py` | Catalog sync history and event-batch request hashes/outcomes with RLS. |
| `migrations/versions/0023_model_deployments.py` | Persist desired/active deployment state and platform aggregate counts. |
| `migrations/versions/0024_recommendation_results.py`, `0025_result_feedback_tenant_fk.py` | Ranked result rows, backfill, RLS, uniqueness and tenant-matched feedback FK. |
| `migrations/versions/0026_customers.py` | Backfill tenant-owned shopper identities and link events/requests with composite FKs. |
| `graphrec_core/database/models.py` | Map new recovery, sync, deployment and result entities/fields. |
| `graphrec_core/customers.py` | Race-safe tenant customer registration shared by event and recommendation flows. |
| `graphrec_core/auth/principal.py`, `auth/service.py`, `schemas/auth.py`, `apps/api/routes/auth.py` | Issue/validate versioned JWTs; operator-assisted one-time recovery and safe redemption. |
| `graphrec_core/catalog/service.py`, `schemas/products.py`, `apps/api/routes/products.py` | Bound, replay and persist catalog syncs, with history/detail reads. |
| `graphrec_core/events/service.py`, `schemas/events.py` | Bound, replay and persist event batch outcomes. |
| `graphrec_core/ingestion/` | Shared request hashing/serialization for durable ingestion replay. |
| `graphrec_core/models_reg/service.py`, `dgsr/worker.py`, `apps/api/routes/model_versions.py` | Training detail/cooldown, artifact indexing, deployment readiness and rollback safety. |
| `graphrec_core/schemas/deployment.py`, `apps/api/routes/deployment.py` | Expose persisted desired/active/readiness state. |
| `graphrec_core/schemas/recommendations.py`, `apps/api/routes/recommendations.py`, `graphrec_core/feedback.py` | Request context/fallback controls, ranked-row persistence and result-linked feedback. |
| `graphrec_core/usage/service.py`, `apps/api/routes/platform.py` | Shared aggregate tenant usage, plan editing, recovery issuance and platform deployment counts. |
| `web/src/api/client.ts`, `client.test.ts`, `index.ts`, `types.ts` | Error presentation plus typed routes and DTOs for added workflows. |
| `web/src/pages/public/RecoverPage.tsx` | Redeem an operator-issued one-time recovery token. |
| `web/src/pages/platform/TenantPages.tsx`, `StatusAuditPages.tsx` | Plan edit, recovery issue, tenant usage and deployment counts. |
| `web/src/pages/tenant/ProductSyncPage.tsx`, `EventsPage.tsx`, `SubmissionPage.tsx` | Durable sync/batch history and per-item outcomes. |
| `web/src/pages/tenant/TrainingPages.tsx`, `ModelsPages.tsx` | Single-job polling, cooldown, readiness and rollback protection. |
| `web/src/pages/tenant/IntegrationPage.tsx`, `ServiceStatusPage.tsx` | Show actual request controls and deployment state. |
| `web/src/pages/tenant/Operations.test.tsx` | Verify operational route/state behavior. |
| `sdks/python/src/graphrec_sdk/_routes.py` | Register added route contract. |
| `sdks/python/src/graphrec_sdk/models/__init__.py`, `models/catalog.py`, `models/events.py`, `models/ml.py`, `models/platform.py`, `models/serving.py` | Typed sync, batch, training, deployment and platform responses; preserve aggregated outcomes. |
| `sdks/python/src/graphrec_sdk/resources/events.py`, `resources/ml.py`, `resources/platform.py`, `resources/products.py`, `resources/recommendations.py`, `resources/tenants.py` | Expose new read/write operations and request controls. |
| `sdks/python/tests/test_contract.py`, `tests/test_resources.py` | Check wire parity and resource methods; distinguish SDK-only aggregate fields. |
| `sdks/typescript/src/routes.ts`, `types.ts` | Typed route and response parity. |
| `sdks/typescript/src/resources/auth.ts`, `events.ts`, `ml.ts`, `platform.ts`, `products.ts`, `recommendations.ts` | Recovery, ingestion, training, plan, usage and serving methods; preserve merged outcomes. |
| `sdks/typescript/tests/contract.test.ts`, `ids.test.ts`, `resources.test.ts` | Contract, route and resource coverage. |
| `tests/integration/test_srs_acceptance.py`, `test_training_worker.py`, `tests/test_recommendation_contract.py` | Cross-layer recovery, ingestion, deployment, result integrity, cooldown and serving validation. |

## 4. API alignment

`Bearer` means a tenant JWT or a tenant API key with the named scope where the route permits it. Operator routes require the separate platform token. OpenAPI is generated by FastAPI at `/openapi.json`.

| SRS operation | Method and endpoint | Credential / scope | Request | Response |
| --- | --- | --- | --- | --- |
| Register tenant | `POST /v1/tenants` | Public, rate/idempotency controls | Registration | Tenant and one-time setup token |
| Sign in / recover | `POST /v1/auth/login`, `/v1/auth/recover-password` | Public, rate limited | Login / recovery token and new password | Token pair / completion |
| Manage credential | `/v1/api-keys*` | Tenant credential scopes | Key settings | Metadata; secret once on create/rotate |
| Product sync / later result | `POST /v1/products:bulk-upsert`; `GET /v1/catalog-syncs[/{id}]` | `catalog:write` / `catalog:read` | Bounded products, optional request ID | Counts, outcomes, sync ID/history |
| Event batch / later result | `POST /v1/events/batches`; `GET /v1/events/batches/{id}` | `events:write` / read scope | Bounded events, optional request ID | Counts, outcomes, batch ID |
| Start / inspect / cancel training | `POST /v1/training-jobs`; `GET /v1/training-jobs/{id}`; `POST /v1/training-jobs/{id}:cancel` | Training write/read | Job configuration, optional request ID | Durable job state |
| Inspect / activate / roll back / archive model | `/v1/model-versions*`, `/v1/models/{id}:rollback` | Model read/deploy | Version/action | Version and safe state |
| Deployment status | `GET /v1/deployment` | Tenant status scope | None | Desired/active, readiness, capacity |
| Recommend | `POST /v1/recommendations` | `recommendations:read` | Shopper/session, count, exclusions, fallback permission | Ranked items and provenance or 503 |
| Submit feedback | `POST /v1/feedback/{impressions,clicks,conversions}` | `events:write` | Served request/rank and event ID | Accepted/duplicate receipt |
| Tenant usage | `GET /v1/usage` | `usage:read` | None | Measured usage/effective quotas |
| Operator tenant usage / recovery | `GET /v1/platform/tenants/{id}/usage`; `POST /v1/platform/tenants/{id}/recovery` | Platform token | Tenant ID; recovery user | Aggregate usage / one-time token |
| Operator plan edit | `PUT /v1/platform/plans/{id}` | Platform token | Bounded plan limits | Updated plan |
| Platform status | `GET /v1/platform/status` | Platform token | None | Worker, serving and deployment counts |

## 5. Database alignment

Existing entities include Tenant, TenantUser, ApiKey, Product, CustomerEvent, EventBatch, DatasetSnapshot and content, TrainingJob, ModelVersion, PricingPlan, TenantSubscription, TenantResourceQuota, UsageEvent, ServingRequest, AuditLog and SecurityEvent. RecommendationRecord is the idempotent response envelope. New CatalogSync, AccountRecoveryToken, ModelDeployment, RecommendationResult and Customer entities map missing durable workflows. A Customer row holds a tenant-owned external shopper ID; it is separate from a console account and carries no personal profile fields.

Migrations `0020`–`0026` add the entities, indexes, tenant RLS, grant/policy changes and backfills noted in section 3. Ranked results have composite tenant/request and tenant/product foreign keys, unique position and product per request, and a tenant-matched feedback foreign key. Accepted events and new recommendation records have composite tenant/customer foreign keys. Deployment has tenant/version ownership. Sync and batch request IDs have tenant-local replay constraints. No database reset was used.

## 6. Activity-diagram traceability

| Decision or action | Backend | Caller/UI | Evidence |
| --- | --- | --- | --- |
| Register, authenticate, recover | `registration/service.py`, `auth/service.py`, `auth/principal.py` | Register, login, recovery and operator tenant pages | Registration, scope and recovery integration tests |
| Derive tenant and authorize action | Principal and `database/tenancy.py` | Route guards and scoped API calls | Isolation and scope tests |
| Validate product/event, register customer, reject or retain result | Catalog/event/customer services and ingestion replay | Product sync, events and submission pages | Acceptance and domain tests |
| Check training sufficiency/quota/cooldown/active job | `models_reg/service.py` | Training form/error state | Worker and acceptance tests |
| Persist stage, cancel and terminal result | `dgsr/worker.py`, model registry | Job detail polling and cancellation dialog | Worker and real-training browser tests |
| Validate activation and keep prior model | Model registry/Qdrant readiness and ModelDeployment | Models and service status pages | Activation failure/rollback tests |
| Validate context/quota/exclusion/fallback | Recommendation schema/route | Storefront SDK and integration example | Recommendation contract/acceptance tests |
| Persist ranked result and validate feedback | Recommendation route, `feedback.py` | Storefront SDK | Result/feedback acceptance and serving tests |
| Show real usage/status/audit | Usage, deployment and platform routes | Usage, service and platform pages | Usage/platform/browser tests |

## 7. Training state machine

Real training starts as a persisted `queued` job. A per-tenant advisory lock prevents concurrent acceptance, a tenant active-job rule and quota apply, and a configurable 60-second cooldown follows a terminal DGSR job. The single CPU worker claims queued work, marks it `running`, persists actual stages/progress (`training`, evaluation and indexing among them), and ends in `succeeded`, `failed` or `cancelled`. A queued cancellation can finish immediately; running cancellation sets a request flag honored at worker checkpoints. Success registers an eligible version and actual metrics; activation is separate. Explicit development-placeholder/import modes retain their provenance and are not presented as fresh training.

## 8. Activation and rollback

A tenant lifecycle lock serializes activation, rollback and archive. Activation checks tenant ownership, status, artifact integrity/loadability and Qdrant index readiness before switching. `ModelDeployment` stores desired, active, readiness and failure state; a failed attempt leaves the previous active version serving. Rollback selects an eligible retired version. Archive refuses the active version and the protected most recent retired rollback target. This is a local service/readiness contract, not proof of a pinned serving replica transition.

## 9. Recommendation pipeline

The API checks shopper/session context, `top_n`, exclusions, quota and request replay. A successful request with a shopper ID registers that identity in the tenant's Customer table. A real DGSR version encodes history and queries its tenant/version Qdrant collection; if Qdrant fails, it can score the local item table. Results are filtered to active, available products in the authenticated tenant, deduplicated, ordered and truncated. With no candidate and fallback allowed, tenant event popularity plus product ID gives a stable order; disabling fallback returns `503 recommendation_unavailable`. The response reports request ID, positions, model version, strategy and fallback tier. RecommendationRecord preserves replay, RecommendationResult persists exact ranked products, and click/conversion feedback references those rows. No learned reranker or Redis/item-neighbor tier exists here.

## 10. Tenant isolation

JWT/API-key authentication derives the tenant; ordinary clients cannot choose a tenant ID. Tenant predicates and forced PostgreSQL RLS cover owned tables. Unknown and foreign resource IDs produce the same safe response where appropriate. Recommendation replay, ranked rows, feedback, product eligibility and usage are tenant keyed; the feedback/result foreign key also checks tenant ownership. Platform APIs use a separate operator token and return aggregate data for selected tenants. Integration tests cover cross-tenant product/job/result access and operator-only reads.

## 11. Verification

Commands ran at the repository root unless noted. Compose applied migration `0026` successfully. The full backend suite was rerun after the customer migration.

| Command | Result |
| --- | --- |
| `docker compose up -d --build api worker frontend` (then rebuilt API/worker after migration edits) | Built and started; migrations through `0026` applied. |
| `docker compose exec -T api python -m pytest -q` | 117 passed, 11 skipped. |
| `docker compose exec -T api python -m pytest -q tests/integration/test_srs_acceptance.py -k 'feedback_replay or catalog_sync_and_event_batch'` | Two targeted flows passed after `0026`. |
| Python SDK: `docker compose run --rm --no-deps -e PYTHONPATH=/app/sdks/python/src -v 'C:\Users\ASUS\Documents\GraphRec\sdks\python:/app/sdks/python:ro' api python -m pytest -q -p no:cacheprovider /app/sdks/python/tests` | Passed. |
| From `sdks/typescript`: `node ./node_modules/typescript/bin/tsc -p tsconfig.json --noEmit` and `node ./node_modules/vitest/vitest.mjs run` | Type check passed; 283 tests passed. |
| `docker compose run --rm --no-deps frontend-test sh -c 'npm ci && npm test -- --run'` | 53 passed. |
| From `web`: `node ./node_modules/@playwright/test/cli.js test` | 16 passed after `0026`, including role isolation, protected rollback/archive and real DGSR training. The training journey also passed after API recreation without restarting nginx. |

The 11 skipped backend tests require separately supplied prepared artifacts. Browser and integration tests exercise the local worker, but do not prove concurrent P95 or abrupt worker recovery. Python and TypeScript SDK tests were rerun after their aggregate-result correction; their route contracts did not change with migration `0026`.

## 12. Remaining SRS gaps

The matrix marks UC-17, 18, 21, 22, 26, 30 and 31 as partial. There is no fresh common-dataset cross-version evaluation, typed hints or rich Customer profile, pinned inference pod, Redis/item-neighbor fallback, RustFS storage, or per-tenant capacity scaling. P95 under supported concurrent load, abrupt worker restart behavior, isolation during capacity changes and exhaustive infrastructure-failure capture remain to be certified. These gaps matter if the full deployment topology and nonfunctional targets are required; they are outside the currently implemented bounded single-node workflow.

## 13. Run instructions

From the repository root in PowerShell, configure `.env` using `.env.example` and distinct database, JWT, API-key, audit and platform secrets. Start the stack with `docker compose up -d --build postgres qdrant migrate api worker frontend`. Migration exits after upgrade. The API is at `http://localhost:8010`, frontend at `http://localhost:5180`, and Qdrant at `http://localhost:6333` unless port overrides are set. Use `docker compose ps` for health and `docker compose logs -f api worker` for backend activity. The worker is required for real training; restart it with `docker compose up -d worker` if stopped.

Run backend tests with `docker compose exec -T api python -m pytest -q`; frontend tests with the Compose command in section 11; TypeScript SDK checks from `sdks/typescript` after `npm ci` if needed; and browser tests from `web` while Compose is running. The Python SDK command bind-mounts its source because it is not copied into the API image. Prepared-artifact tests require compatible artifacts under `MODEL_ARTIFACT_DIR`.

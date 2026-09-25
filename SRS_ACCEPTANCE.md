# GraphRec SRS implementation and acceptance record

Reviewed against `GraphRec_Complete_SRS.md`, verified September 20, 2026. This report distinguishes implemented core behavior from optional enhancements and unverified deployment objectives. It does not certify every SRS statement or production readiness.

## What changed

- Added the Team members console and real invitation/setup flows for tenant administrators and developers. New browser contexts exercise each role and a second isolated tenant.
- Added compatibility with the supplied MovieLens `dgsr-multidata-v4` checkpoint, preserving its configuration, graph fingerprint and weights. Imports require an operator-provisioned identity file. MovieLens is explicitly identified as a public reference dataset; generated tenant artifacts are bound to their owning tenant.
- Implemented durable recommendation records and impression/click/conversion feedback, tenant ownership checks, position validation and replay conflict detection. Recommendation retries meter once and cannot return products disabled since the original response.
- Added artifact integrity/readiness validation before activation and rollback, tenant lifecycle serialization, and audit records for model/training transitions. A failed activation preserves the old active version.
- Replaced count-only snapshot records with persisted, immutable, tenant-scoped contents and a checksum of the actual content. Existing legacy snapshot records are retained; real training requires a newly captured snapshot with contents.
- Added a durable CPU training queue and a separate Compose worker. Real training is the default. Jobs capture tenant data, train DGSR, select a checkpoint using chronological held-out validation, report test and popularity-baseline metrics, support cancellation, and expose progress/failure status. Explicit development placeholders remain available and are labelled accordingly.
- Added training request replay identifiers. The console reuses an identifier when retrying the same dialog submission.
- Enforced catalog, event, training, recommendation, model-storage and active-version admission limits. Recommendation minute-rate and concurrency limits are tenant-scoped. Dataset interaction-log uploads use the same limits. Durable inventory gauges no longer reset incorrectly at a monthly boundary.
- Added current quota reads and audited plan assignment to the platform console. Existing usage and overrides survive a plan change. Platform worker status reflects the actual worker capacity lock.
- Added authenticated API denial audits and a platform timeline combining security events with recorded lifecycle failures. Training quality is displayed as a validation/test/baseline table; real trained models no longer show a placeholder warning.

## Evidence

| Area | Test/evidence | Result recorded so far |
|---|---|---|
| Frontend components | `cd frontend_02; npx vitest run` | 52 tests passed |
| Frontend build | `cd frontend_02; npm run build` | Passed |
| Backend integration | `python -m pytest tests/integration` | 76 passed, including stale-job retry exhaustion and tenant concurrency limits |
| Full browser suite | `cd frontend_02; npx playwright test` | 16 passed in 2.6 minutes against the rebuilt Docker frontend and live API |
| Real model compatibility/integrity | `tests/test_dgsr_serving.py`, `tests/test_movielens_serving.py` | 11 passed with both artifacts explicitly mounted; includes corruption and non-finite-weight rejection |
| New account roles | `frontend_02/e2e/roles.spec.ts` | Passed with new administrators, developer, API key and two tenants |
| Real training through UI | `frontend_02/e2e/training.spec.ts` | Passed: queue → completed model → UI activation → personalized API response |
| Responsive route sweep | `frontend_02/e2e/routes.spec.ts` | Passed; covers both themes and responsive widths |
| MovieLens API workflow | `scripts/verify_movielens.py` | Final rerun passed, including disabled-product replay rejection |

The MovieLens probe imported 7,951 catalog items and 287 real interactions for three trained shoppers. It verified identified and anonymous recommendations, deterministic ranking, feedback persistence/replay, foreign-tenant denial, disabled-product filtering, and failed activation protection. The final 20 warm sequential requests measured P50 44.1 ms and P95 49.0 ms on the local container network. These numbers are not a concurrent-load certification.

Generated browser evidence is in `frontend_02/e2e-screens/`; probe results and **local dummy-account passwords** are in ignored `tests/e2e/results/`. Do not publish the account file. The platform administrator uses the configured operator token, not a fabricated tenant user with a platform role. Shoppers are event identities, not console accounts.

## SRS coverage

| Requirements | Disposition |
|---|---|
| NR-F-01–06 | Registration/setup/login, role gates, credential lifecycle, catalog operations and bounded event submission implemented and exercised. |
| NR-F-07–11 | Real bounded tenant training, progress/cancellation/failure, quality results, activation and rollback implemented. Checkpoint import is a separate supported source. |
| NR-F-12–14 | Identified/session recommendations and durable linked feedback implemented and exercised. |
| NR-F-15–16 | Usage, effective limits, reset information, active model and measured service status implemented. |
| NR-NF-01–03, 05–07 | Credential-derived tenancy, forced database RLS, scoped API keys, safe errors and duplicate-effect protection covered by integration tests. |
| NR-NF-04 | Warm sequential latency measured; supported concurrent-load objective remains to be characterized. |
| NR-NF-08 | Tenant popularity fallback and DGSR in-process scoring are available when the vector index is unavailable. An empty eligible catalog can return an empty result; this is not a readiness guarantee for an unconfigured tenant. |
| ER-F-01–07 | Actual tenant snapshots, tenant-generated parameters, held-out metrics, replay handling, serving identity and validated lifecycle transitions implemented. |
| ER-F-08–09 | Main usage dimensions and admission limits implemented; local single-worker capacity is intentionally tighter than paid-plan concurrency ceilings. No actual autoscaling/replica-runtime accounting is implemented. |
| ER-F-10–12 | Tenant-safe fallback, lifecycle/credential/platform audits and authorized status views implemented. Authenticated API denials and recorded lifecycle failures appear in the platform security/failure timeline. This does not certify capture of every unauthenticated or unexpected infrastructure failure. |
| ER-NF-01–07 | Queue durability, bounded stale-job recovery, ownership, integrity checks, failure recording, deterministic invalid-request termination, stable ordering and resource bounds implemented. A simulated stale heartbeat verifies one retry and visible terminal failure after exhaustion. Abrupt process termination during an actual training batch and supported concurrent load are not yet certified. |
| ER-NF-08–09 | Separate worker/API/model/data/monitoring modules implemented. Some operational dashboards remain narrower than the full SRS monitoring design. |
| XR-F-01, 05, 09 | History + session context, historical rollback and cold-start fallback supported. |
| XR-F-10 | New real training includes a popularity baseline. Model details compare recorded metrics with the active version; comparisons across different evaluation datasets require care and are not a fresh common-dataset evaluation. |
| Other exciting requirements | Scheduled/event-triggered retraining, configurable diversity policies, period trends and tenant autoscaling remain unimplemented. These are not represented as completed. |

## Running the implemented workflow

The final stack runs migration `0019_operational_failures`; API, database, vector store and frontend health checks pass, with the worker running. The integration run temporarily stopped the background worker to exercise queue claims deterministically, then restarted it. The combined backend integration and real-artifact command passed **87 tests**.

1. `docker compose up -d --build api worker frontend` applies migrations and starts the API, durable training worker and console. The served console is at `http://localhost:5180`; the development console uses `http://127.0.0.1:5173`.
2. Register a tenant, activate its initial administrator, then invite another administrator or developer from Team members.
3. Add products and actual chronological shopper interactions. Local training needs at least four interactions for one shopper and at least two distinct items to obtain disjoint training/validation/test targets.
4. On Training, choose **Train from tenant data**. An empty snapshot selector captures current data. Supported local configuration is `{"epochs": 1}` through `10`; default is 3.
5. Local jobs are bounded to 20,000 events, 10,000 catalog items and 180 seconds of processing. One CPU trainer runs globally. Jobs heartbeat during processing; a stale interrupted job is retried once, then fails visibly if its retry budget is exhausted.
6. Review metrics and explicitly activate the eligible version. Submit serving requests using a scoped API credential and reference the returned request ID in feedback.

For checkpoint import, the operator places verified files under `MODEL_ARTIFACT_ROOT/<name>` with `tenant_identity.json`. Private artifacts specify `tenant_id` (or explicitly approved `tenant_ids`). A public reference dataset must specify `public_reference_dataset` and the pinned `checkpoint_sha256`. The public API cannot create or edit these identity files. Generated tenant artifacts live in the persistent `trained_models` volume and carry their snapshot identity.

## Known boundaries

- This is the bounded educational deployment described by the SRS, not a production availability guarantee.
- The SRS acceptance scenario that increases Tenant A's ready capacity while preserving Tenant B's service has not been implemented or verified; the current deployment uses fixed local serving capacity.
- Self-service email password recovery is not implemented. The recovery page provides an operator-contact next step; invitation setup does not reset an already active account.
- Existing asynchronous SDK callers should poll job status until terminal before activating. An empty training request now requests actual training; synthetic behavior requires `configuration.mode = "placeholder"` explicitly.
- Optional Kubernetes/replica autoscaling, multi-node failover, scheduling and advanced ranking policies have not been implemented or certified by this work.
- Original MovieLens datasets/checkpoints are unchanged; copied runtime artifacts and generated test data are separate.

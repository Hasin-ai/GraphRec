# Changelog

## 0.2.0 - 2026-09-12

First complete release of the TypeScript SDK, at feature parity with the Python SDK 0.2.0.

### Added

- `GraphRec` client over the global `fetch`: API-key, password (auto-renewing), access-token and platform-token credentials; `withCredentials()`; per-route credential checks before sending.
- Resources for all 50 server routes: `tenants`, `auth`, `apiKeys`, `subscription`, `usage`, `products`, `events`, `datasets`, `modelVersions`, `trainingJobs`, `deployment`, `metrics`, `recommendations`, `feedback`, `platform`, plus `health()`.
- Typed error hierarchy mapped from the server's error envelope, with `correlationId`, `retryAfterSeconds`, `fieldErrors` and `partialResult` on bulk failures.
- Side-effect-safe retry policy (`Retry-After` honoured; ambiguous failures retried only on idempotent routes; `quota_exceeded` never retried).
- Byte-exact request splitting for `products.bulkUpsert` and `events.createBatch` against the server's 16 KiB body limit, with local duplicate handling that mirrors the server.
- E-commerce layer: `EventTracker`, `EventBuilder`, `CatalogSync`, `RecommendationSession`.
- `deterministicId` producing the same identifiers as the Python SDK, so replayed order webhooks are deduplicated identically across languages.
- Examples: storefront quickstart, tenant onboarding, catalog sync job, order webhook, train-and-deploy, `node:http` storefront, platform admin, end-to-end smoke test (`npm run smoke`).
- Tests: transport, resources, bulk, e-commerce, ids, and a contract suite that reads the FastAPI routers, Pydantic schemas, scope tables and the Python SDK's route table so the SDKs and the server cannot drift.

### Fixed

- `EventTracker.flush()` now sends events that were queued while a previous flush was in flight. Before, a synchronous burst larger than `batchSize` followed by `close()` sent only the first batch.
- Every resource method now returns a rejected promise on local validation failure instead of throwing synchronously, so `.catch()` and `await` behave consistently.
- Constants (`DEFAULT_MAX_BODY_BYTES`, `MAX_TOP_N`, `MAX_EXCLUSIONS`, …) are exported from the package entry point.

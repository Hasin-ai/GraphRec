# Changelog

## 0.2.0 — 2026-09-11

Matches the server's account-setup and scope-enforcement security fixes.

- **Breaking:** `auth.setup_password(setup_token=, password=, email=None)` replaces `setup_password(email=, password=)`. The server no longer activates an account from an email address alone.
- `TenantRegistration.setup_token` and `setup_token_expires_at`: the one-time token from the original `201` response (`None` on an idempotent replay).
- `invalid_setup_token` maps to `AuthenticationError`.
- Every tenant route is now scope-enforced by the server. `Route.required_scopes` and `Route.extra_scopes` describe routes that need more than one scope (`datasets.upload` needs `catalog:write` and `events:write`).
- `ROLE_SCOPES` follows the server: administrators hold every tenant scope; developers also hold `training:read`.
- Contract test for role and delegation scopes, so they can't drift from the server.

## 0.1.0 — 2026-09-11

Initial release covering all 50 GraphRec routes.

- `GraphRec` and `AsyncGraphRec` clients with 15 resources: tenants, auth, api_keys, subscription, usage, products, events, datasets, training_jobs, model_versions, deployment, metrics, recommendations, feedback, platform.
- API-key, bearer-token and email/password credentials. Password auth logs in again automatically when the token expires.
- Retries that are safe for idempotency and honour `Retry-After`. One exception type per server error code.
- Byte-budget chunking for `products.bulk_upsert` and `events.create_batch`, with `partial_result` on failure.
- `graphrec_sdk.ecommerce` helpers: `EventTracker`, `CatalogSync`, `RecommendationSession` (sync and async), and `EventBuilder`.
- Contract tests that parse the FastAPI source so SDK and server can't drift apart.

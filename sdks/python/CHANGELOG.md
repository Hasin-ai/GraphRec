# Changelog

## 1.1.0 — Unreleased

The SDK now shares one version with the GraphRec API and console.

- `storefront.events.list()` / `AsyncEvents.list()` read recently received events (`GET /v1/events`), with `user_id`, `event_type` and `product_id` filters.
- `auth.refresh(refresh_token=...)` rotates a refresh token (`POST /v1/auth/refresh`).
- `GraphRec.meta()` reads the product version.
- `AuthTokenPair.email` carries the signed-in account's email.

## 1.0.0 — 2026-10-04

The SDK now covers all 68 API routes and groups them by audience. This release is **breaking**: every resource moved.

### Breaking changes

- Resources live under three namespaces instead of directly on the client:

  | 0.2.0 | 1.0.0 |
  |---|---|
  | `client.events`, `client.recommendations`, `client.feedback` | `client.storefront.events` / `.recommendations` / `.feedback` |
  | `client.products` | `client.tenant.catalog` |
  | `client.tenants.register`, `client.auth.*` | `client.tenant.auth.register`, `client.tenant.auth.*` |
  | `client.tenant_users` | `client.tenant.users` |
  | `client.api_keys`, `subscription`, `usage`, `datasets`, `model_versions`, `training_jobs`, `deployment`, `metrics` | same names under `client.tenant` |
  | `client.platform.list_tenants()` / `get_tenant` / `set_tenant_status` / `get_tenant_quota` / `get_tenant_usage` / `assign_tenant_plan` / `set_quota_override` / `issue_recovery` | `client.platform.tenants.list()` / `get` / `set_status` / `get_quota` / `get_usage` / `assign_plan` / `set_quota_override` / `issue_recovery` |
  | `client.platform.list_plans()` / `update_plan()` | `client.platform.plans.list()` / `update()` |
  | `client.platform.status()` returned a `dict` | returns a typed `PlatformStatus` |
  | `issue_recovery()` returned a `dict` | returns a typed `RecoveryToken` |

- `EventBatch.outcomes` is a list of `EventItemOutcome` models instead of `dict[str, str]`.
- The resource classes `Tenants` and `Platform` were removed (see the table). `graphrec_sdk.resources` exports `PlatformTenants`, `PlatformPlans`, `PlatformOperations`, `RecommendationPolicyResource` and `RetrainingPolicyResource`.

### Added

- `tenant.auth.logout()` (`POST /v1/auth/logout`). A password-authenticated client forgets its token.
- `tenant.users.revoke_invitation(user_id)` (`DELETE /v1/tenant/users/{id}/invitation`).
- `tenant.usage.trends(granularity=, start=, end=, types=)` (`GET /v1/usage/trends`). Naive datetimes are treated as UTC.
- `tenant.deployment.scaling(limit=)` (`GET /v1/deployment/scaling`), with `ScalingStatus` and `CapacityEvent`.
- `tenant.recommendation_policy.get()/update()` and `tenant.retraining_policy.get()/update()`, with `RecommendationPolicyUpdate` / `RetrainingPolicyUpdate` validated against the server's bounds. `update()` accepts the result of `get()` to change single fields.
- `acknowledge_below_usage=` on `platform.tenants.set_quota_override`, `platform.tenants.assign_plan` and `platform.plans.update`. Responses carry `warnings` (`LimitConflict`). The new `LimitBelowUsageError` (409 `limit_below_usage`) exposes `.conflicts`.
- New response fields: `DeploymentStatus.rate_limiter`, `Recommendations.applied_rules` / `rules_version`.
- Error-code mappings: `invalid_recovery_token` → `AuthenticationError`, `insufficient_role` → `PermissionDeniedError`, `artifact_not_found` → `NotFoundError`.

### Fixed

- `events.create_batch`, `list_batches` and `get_batch` raised `APIResponseValidationError` against a real server, because accepted events have `reason: null`.
- A password-authenticated client stayed signed out after its session was revoked elsewhere (logout, password recovery). It now signs in again once on any `401`, not only on `token_expired`.
- `training_jobs.find()` and `wait()` use `GET /v1/training-jobs/{id}` instead of listing every job.

### Tests

- The contract test checks the new schemas, rejects SDK fields that cannot accept `null` when the server may send it, and checks that every route is reachable from a namespace. Helper calls such as `service.get_product()` are no longer mistaken for route handlers.
- New live suite `tests/integration/test_sdk_live.py` (repository root) runs every SDK route against the real FastAPI app and PostgreSQL, including error paths and tenant isolation.

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

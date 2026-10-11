# GraphRec API

The complete, generated reference is served by every deployment at **`/docs`**
(interactive) and **`/openapi.json`** (the schema; also committed as
`web/openapi.json`, and CI fails when it drifts from the code). This page explains
the conventions that apply to every endpoint. The Python SDK (`sdks/python`)
wraps all of it.

## Base URL and versioning

All endpoints live under `/v1` on the deployment's own origin, e.g.
`https://graphrec.example.com/v1/recommendations`. `GET /v1/meta` reports the
product version (one version for API, console and SDK) and the environment.
Fields are added to responses without a version change; removals or meaning changes
would need `/v2`.

## Authentication

| Caller | Header | Obtained from |
|---|---|---|
| Console user | `Authorization: Bearer <access token>` | `POST /v1/auth/login`; renew with `POST /v1/auth/refresh` (rotating refresh token) |
| Storefront / server integration | `Authorization: ApiKey <secret>` | `POST /v1/api-keys` (an administrator or developer); the secret is shown once |
| Platform operator | `Authorization: Bearer <operator token>` | `POST /v1/platform/auth/login` |

The tenant always comes from the credential; no endpoint accepts a tenant id from
the caller. Each route requires a scope (for example `catalog:write`,
`recommendations:read`); API keys hold only the scopes delegated when they were
created, and some scopes (`keys:write`, `users:write`, `audit:read`) are never
available to API keys.

Public endpoints: `GET /v1/meta`, `GET /v1/plans`, `POST /v1/tenants`
(registration), `POST /v1/auth/login|setup-password|refresh|recover-password`,
`POST /v1/platform/auth/login`, `GET /healthz`, `GET /readyz`.

## Requests

- Bodies are JSON with `Content-Type: application/json` (dataset upload:
  `multipart/form-data`). Unknown fields are rejected, not ignored.
- Size limits: 16 KB for ordinary bodies, 1 MB for product and event batches (up to
  1,000 items), 10 MB for dataset uploads. Larger bodies get `413`.
- Send `X-Correlation-ID: <uuid>` to trace a request; otherwise one is generated.
  Every response carries it back.

## Idempotency and replays

Writes that a client may retry are safe to retry:

- `POST /v1/tenants` requires `Idempotency-Key`. The same key and body replays the
  original response; the same key with a different body is `409`.
- Products are keyed by your `external_id` (`PUT /v1/products/{external_id}` is an
  upsert); bulk upserts accept a `request_id`.
- Events are keyed by your `event_id`: resubmitting returns `duplicate: true` and is
  not counted twice. Batches report an outcome per item.
- Training jobs, recommendations and feedback accept a `request_id`; a replay
  returns the original result without new metering.

## Responses and errors

Every error, from validation to an unexpected failure, has one shape:

```json
{
  "error": {
    "code": "quota_exceeded",
    "message": "The accepted_events limit has been reached.",
    "correlation_id": "6dbe54c8-96bf-43b5-90da-f454caf70f0f",
    "retryable": true,
    "retry_after_seconds": 30,
    "details": { "fields": [ { "field": "period", "message": "Invalid period" } ] }
  }
}
```

| Status | Typical codes | What to do |
|---|---|---|
| 400 / 413 / 415 / 422 | `malformed_request`, `payload_too_large`, `validation_failed` | fix the request; `details.fields` names each field |
| 401 | `authentication_failed`, `token_expired` | sign in again or refresh |
| 403 | `insufficient_scope`, `tenant_inactive` | the credential's role or scopes do not allow this |
| 404 | `resource_not_found` | also returned for other tenants' resources |
| 405 | `method_not_allowed` | |
| 409 | `conflict`, `invalid_state`, `training_in_progress`, `training_cooldown` | the resource is in the wrong state; some carry `Retry-After` |
| 429 | `rate_limit_exceeded`, `quota_exceeded` | wait `Retry-After` seconds; plan quotas reset at the start of the month (UTC) |
| 500 | `internal_error` | retryable; quote the correlation id |
| 503 | `service_unavailable`, `recommendation_unavailable` | retry later, or allow fallback |

Rate-limited routes return `X-RateLimit-Limit`, `X-RateLimit-Remaining` and
`X-RateLimit-Reset`; every `429` has `Retry-After`.

## Pagination

Product lists use `limit` and `offset` and return `total`. Audit trails return
newest first with a keyset cursor: pass the response's `next_before` as `before` to
get the next page.

## Endpoint groups

| Group | Endpoints | Who |
|---|---|---|
| Account | `POST /v1/tenants`, `/v1/auth/*`, `GET /v1/tenant/status`, `/v1/tenant/users*` | public, members, administrators |
| Credentials | `/v1/api-keys*` | administrators, developers |
| Catalog | `/v1/products*`, `/v1/catalog-syncs*` | `catalog:read` / `catalog:write` |
| Events | `/v1/events`, `/v1/events/batches*` | `events:write` / `events:read` |
| Training data | `/v1/datasets/upload`, `/v1/datasets/snapshots*` | `training:*` |
| Training and models | `/v1/training-jobs*`, `/v1/model-versions*`, `/v1/retraining-policy` | `training:*`, `models:*`, `models:deploy` to activate or roll back |
| Serving | `POST /v1/recommendations`, `POST /v1/recommendations/session`, `/v1/feedback/{impressions,clicks,conversions}`, `/v1/recommendation-policy` | `recommendations:read` (storefront API keys) |
| Monitoring | `/v1/deployment*`, `/v1/metrics/summary`, `/v1/usage` (`?period=YYYY-MM`), `/v1/usage/trends`, `/v1/subscription`, `/v1/audit` | administrators |
| Platform | `/v1/platform/*` | operators, by role |

## Recommendations in one call

```bash
curl -s https://graphrec.example.com/v1/recommendations \
  -H "Authorization: ApiKey $GRAPHREC_API_KEY" -H "Content-Type: application/json" \
  -d '{"user_id": "shopper-42", "top_n": 10, "exclude_product_ids": ["sku-in-cart"]}'
```

The response lists products in rank order with the `strategy` used
(`personalized`, `session`, or `popular_fallback`), whether a fallback served it,
and which model version produced it (`null` when none did). Set
`"fallback_allowed": false` to get `503 recommendation_unavailable` instead of a
popularity list. Anonymous shoppers send `context.session_id` and
`context.recent_product_ids`.

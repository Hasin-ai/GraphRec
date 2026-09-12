# GraphRec TypeScript SDK

Typed TypeScript/JavaScript client for the GraphRec multi-tenant recommendation platform. It covers the whole API: catalog sync, customer events, recommendations and feedback for storefront backends; tenant administration (auth, API keys, datasets, training, model versions, deployment, usage); and platform operations.

- One `GraphRec` client built on the global `fetch`; works in Node 18.17+ (and Bun/Deno). No runtime dependencies.
- TypeScript types for every request and response. Response types are open, so a newer server won't break an older SDK.
- Automatic retries that never duplicate side effects. `Retry-After` is honoured.
- One error class per server error code, each carrying the server's `correlationId`.
- Password login that renews the 15-minute access token for you (the API has no refresh endpoint).
- Bulk calls split their payload automatically to fit GraphRec's 16 KiB request-body limit.
- E-commerce helpers: a buffered `EventTracker`, `CatalogSync` (can disable products that dropped out of the feed), and `RecommendationSession` for impression, click and conversion bookkeeping.
- Byte-for-byte compatible with the [Python SDK](../python): same route table, same error codes, same deterministic event IDs.

---

## Installation

From the GraphRec repository:

```bash
npm install ./sdks/typescript            # or: cd sdks/typescript && npm run build && npm link
```

The package is ESM (`import`), ships type declarations and exposes two entry points: `@graphrec/sdk` and `@graphrec/sdk/ecommerce`.

## Quickstart: storefront backend

Create an API key under **Integration → API keys** (or see [Tenant onboarding](#tenant-onboarding)). Then:

```ts
import { GraphRec } from "@graphrec/sdk";
import { EventTracker, RecommendationSession } from "@graphrec/sdk/ecommerce";

const client = new GraphRec({ baseUrl: "http://localhost:8010", apiKey: "gr_live_..." });

// 1. Catalog
await client.products.bulkUpsert([
  { external_id: "sku-100", title: "Linen shirt", price: "49.90", category: "shirts", metadata: { brand: "Acme" } },
  { external_id: "sku-101", title: "Chino trousers", price: "59.00", category: "trousers" },
]);

// 2. Behaviour (buffered, batched, idempotent)
const tracker = new EventTracker(client, { batchSize: 100, flushIntervalMs: 5000 });
tracker.view("customer-42", "sku-100", { sessionId: "sess-1" });
tracker.addToCart("customer-42", "sku-100", { quantity: 1, price: "49.90" });
tracker.purchase("customer-42", "sku-100", { orderId: "ORD-1001" }); // replay-safe
await tracker.close();

// 3. Recommendations + feedback
const widget = new RecommendationSession(client); // records impressions automatically
const recs = await widget.recommend({ userId: "customer-42", topN: 6, excludeProductIds: ["sku-100"] });
console.log(recs.strategy, recs.fallback_used, recs.items.map((i) => i.external_product_id));
await widget.click(recs, recs.items[0].external_product_id); // position + impression linked for you
await widget.convert(recs, recs.items[0].external_product_id, { value: "59.00" });
```

More in [`examples/`](examples) (run them with `npm run build && node examples/<name>.ts`; Node 22.6+ strips the types itself):

| Example | Shows |
|---|---|
| `storefront-quickstart.ts` | Catalog, tracking, recommendations and feedback |
| `tenant-onboarding.ts` | Register a tenant, activate the admin with the setup token, mint a storefront key |
| `catalog-sync-job.ts` | Nightly CSV sync with `disableMissing` and an exit code |
| `order-webhook.ts` | Purchase events that are safe when the webhook is redelivered |
| `train-and-deploy.ts` | Snapshot, train, review, activate and roll back |
| `http-storefront.ts` | The SDK inside a `node:http` backend with a background tracker |
| `platform-admin.ts` | Plans, tenants, quota overrides, failures and audit with the platform token |
| `end-to-end-smoke.ts` | Every SDK area against a running `docker compose` stack (`npm run smoke`) |

---

## Authentication

| Credential | Constructor | Header | Use for |
|---|---|---|---|
| API key | `new GraphRec({ apiKey: "gr_live_…" })` | `ApiKey gr_live_…` | Storefront and server-to-server integration |
| Email and password | `new GraphRec({ email, password })` | `Bearer <jwt>` | Admin scripts. Logs in on first use and again before the token expires or on `token_expired` |
| Access token | `new GraphRec({ accessToken })` | `Bearer <jwt>` | Tokens you manage yourself |
| Platform admin token | `new GraphRec({ platformToken: PLATFORM_ADMIN_TOKEN })` | `Bearer <secret>` | `client.platform` only (the server's shared secret from `.env`) |
| None | `new GraphRec()` | none | `tenants.register`, `auth.*`, `health()` |

If no credential is passed, the client reads `GRAPHREC_API_KEY` or `GRAPHREC_ACCESS_TOKEN`, and `GRAPHREC_BASE_URL` (default `http://localhost:8010`). Pass `useEnv: false` to turn that off.

Credentials are never sent to public routes. API-key management (`client.apiKeys`) only accepts a user's bearer token, and `client.platform` only accepts the `PLATFORM_ADMIN_TOKEN` bearer. The SDK throws `ConfigurationError` before sending a request that can't succeed.

`withCredentials()` returns a client for the same server with different credentials:

```ts
const publicClient = new GraphRec({ useEnv: false });
const admin = publicClient.withCredentials({ email: "owner@shop.example", password: "…" });
const key = await admin.apiKeys.create({ name: "web", scopes: STOREFRONT_KEY_SCOPES });
const store = publicClient.withCredentials({ apiKey: key.secret });
```

### Tenant onboarding

Registration creates the tenant and an *invited* administrator. The `201` response carries a one-time `setup_token` that activates that account:

```ts
const publicClient = new GraphRec({ useEnv: false });
const tenant = await publicClient.tenants.register({ name: "Acme Outfitters", admin_email: "owner@acme.example" });
await publicClient.auth.setupPassword({ setupToken: tenant.setup_token!, password: "a-long-password", email: "owner@acme.example" });
const admin = publicClient.withCredentials({ email: "owner@acme.example", password: "a-long-password" });
```

The token expires (`setup_token_expires_at`, 24 hours by default), works once, and only activates accounts that are still invited. Treat it like a password. It is not returned again: a replayed registration has `replayed: true` and `setup_token: null`. If it is lost or expired, an operator issues a new one:

```bash
docker compose exec api python -m scripts.issue_account_setup_token owner@acme.example
```

Any rejected token throws `AuthenticationError` with `code === "invalid_setup_token"`.

### Scopes

Users get their scopes from their role: administrators hold every tenant scope, developers hold `keys:write`, `catalog:*`, `events:*` and `training:read`. Access tokens keep the scopes granted at login, so sign in again after a role change. An API key gets the scopes chosen when it's created, limited to what the creating role may delegate. Administrators can delegate any scope; developers only `catalog:*` and `events:*`. The server checks the scope on every tenant route and answers `403 insufficient_scope` (`PermissionDeniedError`) when it is missing.

| Preset | Scopes |
|---|---|
| `STOREFRONT_KEY_SCOPES` | `catalog:read`, `catalog:write`, `events:read`, `events:write`, `recommendations:read` (the last one needs an administrator to delegate it) |
| `CATALOG_SYNC_KEY_SCOPES` | `catalog:read`, `catalog:write` |

Every scope is in the `Scope` union type. `ROLE_SCOPES` and `DELEGATABLE_SCOPES` mirror the server.

---

## API reference

Every method maps to exactly one route (`products.update` and the `wait`/`find`/`getActive` helpers are the documented exceptions). The **Scope** column lists the scopes the credential needs; the server enforces all of them. `requiredScopes(route(key))` has the same information in code.

| Resource | Method | HTTP | Scope |
|---|---|---|---|
| `client` | `health()` | `GET /healthz` | – |
| `tenants` | `register({ name, admin_email }, { idempotencyKey? })` | `POST /v1/tenants` | public |
| `auth` | `login({ email, password })` | `POST /v1/auth/login` | public |
| | `setupPassword({ setupToken, password, email? })` | `POST /v1/auth/setup-password` | public (one-time token) |
| `apiKeys` | `list()` / `get(keyId)` | `GET /v1/api-keys[/{id}]` | `keys:write` ✔ bearer |
| | `create({ name, scopes, expiresAt? \| expiresInDays? })` | `POST /v1/api-keys` | `keys:write` ✔ bearer |
| | `rotate(keyId, { reason, gracePeriodSeconds? })` | `POST /v1/api-keys/{id}/rotate` | `keys:write` ✔ bearer |
| | `revoke(keyId)` | `DELETE /v1/api-keys/{id}` | `keys:write` ✔ bearer |
| `subscription` | `get()` | `GET /v1/subscription` | `billing:read` ✔ |
| `usage` | `get()` / `dimension("accepted_events")` | `GET /v1/usage` | `usage:read` ✔ |
| `products` | `bulkUpsert(products, { idempotencyKey? })` | `POST /v1/products:bulk-upsert` | `catalog:write` ✔ |
| | `list()` / `get(externalId)` | `GET /v1/products[/{id}]` | `catalog:read` ✔ |
| | `upsert(product)` | `PUT /v1/products/{id}` | `catalog:write` ✔ |
| | `update(externalId, changes)` (read, merge, write) | `GET` then `PATCH /v1/products/{id}` | `catalog:write` ✔ |
| | `disable(externalId)` | `POST /v1/products/{id}:disable` | `catalog:write` ✔ |
| `events` | `create({ event_type, user_id?, external_product_id?, context?, occurred_at?, event_id? })` | `POST /v1/events` | `events:write` ✔ |
| | `createBatch(events)` | `POST /v1/events/batches` | `events:write` ✔ |
| | `listBatches()` / `getBatch(batchId)` | `GET /v1/events/batches[/{id}]` | `events:read` ✔ |
| `datasets` | `upload(blob \| string \| bytes, { filename?, contentType? })` | `POST /v1/datasets/upload` (multipart) | `catalog:write` + `events:write` ✔ |
| | `createSnapshot({ cutoffAt?, description? })` | `POST /v1/datasets/snapshots` | `training:write` ✔ |
| | `listSnapshots()` / `getSnapshot(id)` | `GET /v1/datasets/snapshots[/{id}]` | `training:read` ✔ |
| `trainingJobs` | `create({ model_type?, dataset_snapshot_id?, configuration? })` | `POST /v1/training-jobs` | `training:write` ✔ |
| | `list()`, `find(jobId)`, `wait(jobId, { timeoutMs?, pollIntervalMs? })` | `GET /v1/training-jobs` | `training:read` ✔ |
| `modelVersions` | `create({ version_tag, model_type, metrics?, artifact_uri? })` | `POST /v1/model-versions` | `models:write` ✔ |
| | `list()`, `get(id)`, `getActive()` | `GET /v1/model-versions[/{id}]` | `models:read` ✔ |
| | `activate(id)` / `rollback(id)` | `POST /v1/model-versions/{id}:activate`, `POST /v1/models/{id}:rollback` | `models:deploy` ✔ |
| | `archive(id)` | `POST /v1/model-versions/{id}:archive` | `models:write` ✔ |
| `deployment` | `get()`, `replicas()`, `autoscaling()` | `GET /v1/deployment[/replicas\|/autoscaling]` | `deployments:read` ✔ |
| `metrics` | `summary()` | `GET /v1/metrics/summary` | `metrics:read` ✔ |
| `recommendations` | `get({ userId?, topN?, context?, excludeProductIds? })` | `POST /v1/recommendations` | `recommendations:read` ✔ |
| | `forSession({ sessionId, recentProductIds?, … })` | `POST /v1/recommendations/session` | `recommendations:read` ✔ |
| `feedback` | `impression(recsOrRequestId, { items?, … })` | `POST /v1/feedback/impressions` | `events:write` ✔ |
| | `click(recsOrRequestId, productId, { position?, impressionEventId?, … })` | `POST /v1/feedback/clicks` | `events:write` ✔ |
| | `conversion(recsOrRequestId, productId, { value?, … })` | `POST /v1/feedback/conversions` | `events:write` ✔ |
| `platform` | `listTenants()`, `getTenant(id)`, `setTenantStatus(id, "suspended")` | `/v1/platform/tenants…` | `PLATFORM_ADMIN_TOKEN` ✔ |
| | `listPlans()`, `setQuotaOverride(id, overrides)` | `/v1/platform/plans`, `…/quotas` | `PLATFORM_ADMIN_TOKEN` ✔ |
| | `listFailures()`, `listAuditLogs()`, `status()` | `/v1/platform/failures\|audit\|status` | `PLATFORM_ADMIN_TOKEN` ✔ |

Wire field names are the server's `snake_case`; method options are `camelCase`. Every method returns a `Promise`, including when local validation fails (`InputValidationError` is a rejection, never a synchronous throw). String enumerations (`EventType`, `ModelStatus`, `TrainingStatus`, `AvailabilityStatus`, `TenantStatus`, `UsageType`…) are exported as union types and accept unknown future values.

---

## E-commerce helpers

### `EventTracker`

A buffer that sends events through `events.createBatch`.

- Flushes automatically every `batchSize` events, every `flushIntervalMs` milliseconds (the timer is `unref`'d so it never keeps a process alive), and on `close()` / `await using`.
- If a flush fails, the events go back in the queue once (bounded by `maxQueueSize`) and the promise rejects. Pass `onError` to log and drop them instead. Background flushes never surface as unhandled rejections.
- Typed helpers: `view`, `click`, `addToCart`, `removeFromCart`, `purchase`, `rating`, `search`, `addToWishlist`, plus `track()` and `custom()` for any event type. Custom attributes go in `context`, and `defaultContext` is merged into every event.
- `purchase(…, { orderId, line })` derives the event ID from the order line (`deterministicId`), so a redelivered webhook is recorded only once. The Python SDK derives the identical ID.

### `CatalogSync`

```ts
const report = await new CatalogSync(client).run(feedRows, { disableMissing: true });
console.log(report.summary()); // created=… updated=… rejected=… disabled=… requests=…
```

The sync validates rows locally, drops duplicate IDs the same way the server does, and splits the upload into requests that fit the body limit. With `disableMissing`, active products absent from the feed are disabled. An empty feed with `disableMissing` is refused unless you pass `allowEmpty: true`, so a broken export can't switch off your whole catalog.

### `RecommendationSession`

`recommend()` calls `recommendations.get` (or `forSession` when you pass `sessionId`) and sends the impression. `click()` and `convert()` look up the item's position and link the impression automatically. If the click happens in another process, persist `recs.request_id` and call `client.feedback.click(requestId, productId, { position })` directly.

---

## Errors

```
GraphRecError
├── ConfigurationError            client can't make this call (missing or wrong credential type)
├── InputValidationError          arguments rejected locally; nothing was sent
├── WaitTimeoutError              polling helper gave up
└── APIError                      .message .correlationId .request
    ├── APIConnectionError        DNS, refused connection, TLS (.cause)
    │   └── APITimeoutError
    ├── APIResponseValidationError  2xx body wasn't JSON (.body)
    └── APIStatusError            .status .code .retryable .retryAfterSeconds .details .body
        ├── MalformedRequestError      400 malformed_request
        ├── AuthenticationError        401 authentication_failed / invalid_setup_token
        │   └── TokenExpiredError      401 token_expired
        ├── PermissionDeniedError      403 insufficient_scope
        ├── NotFoundError              404 resource_not_found
        ├── ConflictError              409
        │   ├── DuplicateResourceError     duplicate_resource
        │   ├── IdempotencyConflictError   idempotency_conflict
        │   └── StateConflictError         state_conflict / conflict
        ├── PayloadTooLargeError       413 payload_too_large
        ├── RequestValidationError     422 validation_failed (.fieldErrors)
        ├── RateLimitError             429 rate_limit_exceeded
        ├── QuotaExceededError         429 quota_exceeded
        └── InternalServerError        5xx
            └── ServiceUnavailableError  503 service_unavailable
```

If a request fails partway through a bulk call (`products.bulkUpsert`, `events.createBatch`), the error has a `partialResult` property with the totals the server already accepted.

### Retries

`retry.maxRetries` (default 2) applies with exponential backoff and jitter.

| Failure | Retried for |
|---|---|
| `429 rate_limit_exceeded`, `503` with `retryable: true` | every route (the server rejected the request before doing anything) |
| Connection refused, DNS failure | every route (nothing was sent) |
| Timeout, dropped connection, 502/504 | idempotent routes only: reads, upserts, and writes deduplicated by `event_id` or `Idempotency-Key` |
| `quota_exceeded`, every other 4xx, 500 | never |

Non-idempotent calls (`apiKeys.create`/`rotate`, `trainingJobs.create`, `modelVersions.create`, `datasets.*` writes) are not retried after ambiguous failures.

---

## Configuration

```ts
import { GraphRec } from "@graphrec/sdk";

const client = new GraphRec({
  baseUrl: "https://graphrec.internal",
  apiKey: "gr_live_…",
  timeoutMs: 5_000,                                  // default 30 s, per attempt
  retry: { maxRetries: 4, maxRetryAfterSeconds: 30 },
  maxBodyBytes: 16_384,                              // match the server's MAX_REQUEST_BODY_BYTES
  maxBatchItems: 500,
  defaultHeaders: { "X-Shop-Region": "eu" },
  fetch: myInstrumentedFetch,                        // optional: proxies, tracing, polyfills
});
```

Pass `correlationId` in `client.request(routeKey, options)` to set `X-Correlation-ID` yourself; otherwise the server generates one and every error carries it back.

## Testing your integration

Pass a `fetch` that answers from memory. No network is needed:

```ts
import { GraphRec } from "@graphrec/sdk";

const fakeFetch: typeof fetch = async (url) => {
  if (!String(url).endsWith("/v1/recommendations")) throw new Error(`unexpected ${url}`);
  return new Response(JSON.stringify({ request_id: "rec-1", items: [], strategy: "popular_fallback", fallback_used: true, fallback_tier: "tenant_popular" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

const client = new GraphRec({ apiKey: "gr_live_test", useEnv: false, fetch: fakeFetch });
console.assert((await client.recommendations.get({ userId: "u1" })).fallback_used);
```

---

## Server compatibility notes

The SDK is kept in lockstep with the API in this repository by `tests/contract.test.ts`, which reads the FastAPI routers, Pydantic schemas and scope tables and also compares the route table with the Python SDK's. Current platform limitations the SDK works around or documents:

- **No token refresh endpoint.** Password credentials log in again instead.
- **`PATCH /v1/products/{id}` needs a full product.** `products.update()` reads the product, merges your changes and writes it back, so it isn't atomic.
- **No single training-job endpoint and no pagination.** `trainingJobs.find()` and `wait()` poll the list.
- **Training runs synchronously today** and indexes placeholder embeddings without offline metrics. `wait()` returns right away and keeps working once training becomes asynchronous.

## Development

```bash
cd sdks/typescript
npm install
npm run typecheck      # strict tsc over src, tests and examples
npm test               # vitest: transport, resources, bulk, e-commerce, ids, contract
npm run build          # dist/ (ESM + .d.ts)
npm run check          # all three
npm run smoke -- --base-url http://localhost:8010   # against docker compose
```

`tests/contract.test.ts` checks the route table (`ROUTES`), the wire types in `src/types.ts` and the bodies the SDK actually sends against the FastAPI routers and Pydantic schemas. If an endpoint, body type, auth rule, enforced scope or schema field changes on the server — or the Python SDK's table diverges — that test fails.

# `@graphrec/sdk`

A client for the GraphRec API, for **Node 20 or newer, on your server**.

## It does not run in a browser, and that is not an oversight

Every call this SDK makes carries a `gr_live_` credential, and that credential
is a bearer token: whoever holds it can read one tenant's catalogue, write its
events and spend its quota. Shipped to a browser it is in the bundle, in the
devtools network tab and in the extension that reads both. There is no
public-key variant, no origin restriction and no per-session scope-down that
would make it safe to send, so the SDK does not pretend otherwise — `package.json`
has no `browser` field, no UMD build and no CDN entry.

The shape that works is the ordinary one: your browser talks to your server,
your server holds the credential and calls GraphRec. That also puts your own
identity check in front of every recommendation, which is the check GraphRec
cannot make for you.

Two more consequences of the same reasoning, both load-bearing:

- **Both GraphRec edges require TLS 1.3.** A runtime pinned to an old OpenSSL
  fails the handshake, and a handshake failure has no HTTP status to look up.
  Node 20's bundled OpenSSL is fine.
- **There is no CORS on the data plane.** `deploy/n3/Caddyfile` sets no
  `Access-Control-Allow-Origin`, because a header written for a browser on a
  path that has no browser is a header nobody reads.

## Install

```sh
npm install @graphrec/sdk
```

## Two hosts, one client

GraphRec answers on two hostnames. The **control plane** — catalogue, events,
submissions — is one host shared by every tenant. The **data plane** —
recommendations and feedback — is a host **per tenant**, because N3's edge
resolves your replicas from the subdomain rather than from the path or the
credential. A single base URL cannot express that, so the SDK takes your domain
and derives both:

<!-- example: construct -->
```ts
const gr = new GraphRec({
  apiKey: process.env.GRAPHREC_API_KEY!,
  tenantId: process.env.GRAPHREC_TENANT_ID!,
  domain: 'graphrec.example',
});
```

That yields `https://api.graphrec.example` for the control plane and
`https://<tenant-hex>.serve.graphrec.example` for the data plane. If your estate
parameterises the two independently — it can; they are `GRAPHREC_CONSOLE_DOMAIN`
and `GRAPHREC_API_DOMAIN` — pass `consoleDomain` and `apiDomain` instead, or
`controlUrl` and `dataUrl` to override the origins outright.

The tenant id may be dashed as the console prints it or bare hex as the hostname
needs it; the SDK normalises. Nothing in the surface lets a call choose its host:
each namespace is bound to one at construction, so routing a control-plane call
at the data plane is not a mistake you can make.

## Recommendations

<!-- example: recommend -->
```ts
const answer = await gr.recommendations.forCustomer({
  requestId: crypto.randomUUID(),
  customerId: 'customer-1',
  topN: 10,
  recentEvents: [{ externalProductId: 'sku-1', eventType: 'view' }],
  excludeProductIds: ['sku-9'],
});

for (const item of answer.items) {
  console.log(item.rank, item.externalProductId, item.score);
}
```

`forSession` is the same call for a visitor you have no customer id for. Both are
`POST`s, both are safe to retry, and the SDK does retry them within your timeout
budget.

## Feedback

Feedback closes the loop: an impression says the items were shown, a click says
one was chosen, a conversion says one was bought. All three take the `requestId`
of the recommendation they refer to.

<!-- example: feedback -->
```ts
await gr.feedback.impressions({
  requestId: answer.requestId,
  events: answer.items.map((item) => ({
    eventId: `${answer.requestId}:${item.externalProductId}`,
    externalProductId: item.externalProductId,
  })),
});

await gr.feedback.conversions({
  requestId: answer.requestId,
  events: [{ eventId: 'order-4471', externalProductId: 'sku-1', value: 19.99 }],
});
```

## Catalogue

A bulk upsert is accepted, not applied — it returns a submission you poll.

<!-- example: catalog -->
```ts
const accepted = await gr.catalog.sync({
  syncId: '2026-08-24-nightly',
  mode: 'upsert',
  products: [
    {
      externalId: 'sku-1',
      title: 'Example product',
      category: 'example',
      price: '19.99',
      availability: 'in_stock',
    },
  ],
});

const finished = await gr.submissions.wait(accepted.submissionId, { timeout: 120_000 });
console.log(finished.counts);
```

`mode: 'upsert_and_disable_missing'` disables every product **not** in the
request. On a full catalogue that is what you want. On one page of a paginated
export it empties the shop, and the SDK cannot tell the two apart.

## Events

<!-- example: events -->
```ts
const receipt = await gr.events.submit({
  eventId: '11111111-1111-4111-8111-111111111111',
  customerId: 'customer-1',
  externalProductId: 'sku-1',
  eventType: 'view',
  occurredAt: new Date(),
});

if (receipt.status === 'duplicate_confirmed') {
  console.log('already had it, first seen at', receipt.firstReceivedAt);
}
```

`occurredAt` is required and must carry a timezone. A `Date` always does; a
string must be ISO 8601 with an offset, because a naive timestamp is refused
rather than assumed to be UTC.

## Idempotency

**The SDK never invents an identifier.** `eventId`, `syncId`, `batchId` and
`requestId` are yours, and a repeat carrying the same one is deduplicated by the
server and answered with a success rather than a 409. A generated id would be a
different id on every attempt, which would turn the SDK's own retry into a second
write — deduplication silently disabled by a convenience. So a call that needs an
identifier requires one, and a retry sends the one you gave, byte for byte.

`Idempotency-Key` is not used. It appears in the API's CORS allowlist and no
handler reads it; the key is in the body.

## Errors

Every failure is a `GraphRecError` subclass carrying the server's `code`,
`reason`, `reference` (your `X-Request-Id`, echoed) and `fieldErrors`. The class
follows the error's class and status, so `catch` can be specific:

| Class | Status | Meaning |
| --- | --- | --- |
| `ValidationError` | 422 | The request is malformed. `fieldErrors` says where. |
| `ConflictError` | 409 | The state does not permit it. |
| `RateLimitedError` | 429 | Too fast. Carries `retryAfterSeconds`. |
| `QuotaExhaustedError` | 429 | Allowance spent. **Waiting does not help.** |
| `AuthenticationError` | 401, 403 | Bad credential, or one without the scope. |
| `NotFoundError` | 404 | No such thing, for this tenant. |
| `UnavailableError` | 503 | Transient. Retried automatically. |
| `InternalError` | 500 | Ours. Retried automatically. |
| `TimeoutError` | — | Your budget elapsed. |
| `TransportError` | — | The connection failed. Check TLS 1.3. |

The two 429s share a status and a class and need opposite handling, which is why
they are separate types:

<!-- example: errors -->
```ts
try {
  const answer = await gr.recommendations.forCustomer({
    requestId: crypto.randomUUID(),
    customerId: 'customer-1',
  });
  return answer.strategy;
} catch (error) {
  if (error instanceof QuotaExhaustedError) {
    // Waiting will not help: the allowance resets with the billing period.
    return 'quota';
  }
  if (error instanceof RateLimitedError) {
    // The SDK already retried within your timeout budget.
    return 'rate-limited';
  }
  if (error instanceof UnavailableError) {
    // No ready model, and `allowFallback: false` was set somewhere upstream.
    return 'unavailable';
  }
  throw error;
}
```

`PermissionError` is a subclass of `AuthenticationError` so that a `catch` on the
latter covers both — the API reports 403 with `"class": "auth"`, and the SDK
keeps that shape rather than inventing a `forbidden` class the server never
sends.

A submission that finishes in `failed` throws only from `wait`; `submissions.get`
returns it as a value, because a failed submission is an answer.

<!-- example: submission-errors -->
```ts
try {
  await gr.submissions.wait('submission-id');
} catch (error) {
  if (error instanceof SubmissionFailedError) {
    return error.submission.errors.map((item) => `${item.ref}: ${item.reason}`);
  }
  throw error;
}
return [];
```

## Retries and the timeout budget

`timeout` is a budget for the **whole call**, retries included, and it defaults to
10 s. `maxRetries` defaults to 2. An attempt is retried only when all of these
hold:

1. the call is idempotent — every route here is, given your identifier;
2. the server said the condition was transient, by `retryable: true` or by naming
   a `retry_after_seconds`;
3. the next attempt fits inside the remaining budget.

Backoff is exponential with full jitter from 250 ms, capped at 8 s, except when
the server named a wait, in which case the server's number wins. A
`QuotaExhaustedError` reports neither `retryable` nor a wait, so it is attempted
exactly once — a retry loop against a spent allowance is a loop that spends the
next period's too.

Pass `signal` on any call to cancel it yourself; your abort propagates
untouched rather than being dressed up as a `TimeoutError`.

## The credential never leaks

The secret half of the key lives in a `#private` field, so it is absent from
`JSON.stringify`, from `util.inspect`, from a structured logger's serialisation
of the client, and from the crash reporter that ships all three somewhere else.
The public prefix stays visible — `client.credentialPrefix` — because a support
conversation needs to name a key without quoting it.

## Bounds

The SDK checks the published limits before spending a round trip on a request the
server will refuse, and raises the same `ValidationError` with the same code the
server would, minus the `reference`:

| | |
| --- | --- |
| `topN` | ≤ 100 |
| `recentEvents` | ≤ 50 |
| `excludeProductIds` | ≤ 200 |
| products per sync | ≤ 5000 |
| events per batch | ≤ 5000 |
| catalogue `externalId` | ≤ 120 characters |
| data-plane ids | ≤ 200 characters |

The two planes disagree on id length deliberately: the ingestion column has a
`ck_*_external_id_length` constraint at 120, and the data plane accepts a longer
id so that a lookup for something never ingested returns "not found" rather than
"invalid".

These are the defaults of a standard estate. A self-hosted deployment can
configure them lower, and the server remains the authority.

## Scopes

A key carries scopes, and a call with the wrong ones is a 403.

| Namespace | Scope |
| --- | --- |
| `catalog` | `catalog:write` |
| `events` | `events:write` |
| `submissions` | `submissions:read` |
| `recommendations` | `recommendations:read` |
| `feedback` | `feedback:write` |

## Development

```sh
npm install
npm run typecheck
npm test
npm run build
```

The test suite holds the contract against the repository it is in: the route
table is checked against `frontend/openapi.json`, the host derivation against
`deploy/n3/Caddyfile` and `graphrec/serving_driver/compose.py`, the error classes
against `graphrec/common/errors.py`, and every code block in this file against
`test/examples.ts`, which is compiled and executed. A drift on either side turns
a suite red rather than a customer's integration.

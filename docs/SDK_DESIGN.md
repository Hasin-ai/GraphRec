# The client SDK

This document designs the libraries a customer's own service uses to call
GraphRec. It is a design, not an implementation: every decision below states
what is being chosen, what was rejected, and which failure the choice prevents.

The audience is a backend engineer at a tenant who has been handed a credential
and a base URL and has to get recommendations into a product page by Friday.
Everything here is measured against that person.

---

## 1. What the SDK covers

Ten routes, on two hosts. This is the whole public integration surface; the
rest of the API is the console's, and the console is not an SDK customer.

| Route | Host | Scope | Idempotent on |
| --- | --- | --- | --- |
| `POST /v1/products:bulk-upsert` | control | `catalog:write` | `sync_id` |
| `POST /v1/events` | control | `events:write` | `event_id` |
| `POST /v1/events/batches` | control | `events:write` | `batch_id` |
| `GET /v1/events/batches/{batch_id}` | control | `submissions:read` | — |
| `GET /v1/submissions/{submission_id}` | control | `submissions:read` | — |
| `POST /v1/recommendations` | data | `recommendations:read` | `request_id` |
| `POST /v1/recommendations/session` | data | `recommendations:read` | `request_id` |
| `POST /v1/feedback/impressions` | data | `feedback:write` | `request_id` + `event_id` |
| `POST /v1/feedback/clicks` | data | `feedback:write` | `request_id` + `event_id` |
| `POST /v1/feedback/conversions` | data | `feedback:write` | `request_id` + `event_id` |

Two of these are not on the `/integration` page and should be:
`GET /v1/events/batches/{batch_id}` and `POST /v1/recommendations/session`.
Both are in `frontend/openapi.json` with a `servers` block, both are reachable
with a credential, and a customer who wants session-only recommendations
currently has to read the OpenAPI document to discover the route exists. The SDK
covers all ten; §12 records this as a defect against the page.

**Not covered.** Sign-in, refresh, user management, plans, training, model
activation, deployment, usage. Those are session-realm operations that a person
performs in the console. An SDK that wrapped them would be inviting customers to
put a human's refresh token in a server process, which is precisely the confusion
the two realms exist to prevent (`apps/control_api/deps.py`).

---

## 2. The contract, as it actually is

Five facts drive every decision below. Each was read out of the code rather than
out of the documentation, and two of them contradict the documentation.

### 2.1 Two hosts, and the tenant is in the hostname

- Control plane: `https://api.{your-domain}` — one host for every tenant.
- Data plane: `https://{tenant_id_hex}.serve.{your-domain}` — one host **per
  tenant**.

N3's Caddy resolves the upstream from the subdomain
(`graphrec-serve-{http.request.host.labels.3}-inference`, `deploy/n3/Caddyfile`
line 69) and the label is the tenant's UUID in hex, without dashes — the same
value `graphrec/serving_driver/compose.py` uses as its Compose project name.

A single `baseUrl` constructor argument is therefore wrong, and wrong in the
quietest possible way: `POST https://api.example/v1/recommendations` is a 404
with nothing in the body to explain it, because that route does not exist on
that application. §4 is about making that mistake unrepresentable.

### 2.2 The credential is a bearer token, not a request signature

`apps/inference/deps.py` line 92 takes `HTTPAuthorizationCredentials` from
`fastapi.security.HTTPBearer`; `_token()` at line 176 rejects any scheme other
than `bearer` and returns the string unchanged. `apps/control_api/deps.py` does
the same through `_bearer_token`.

```
Authorization: Bearer gr_live_7Kq4.<43 url-safe characters>
```

The HMAC-SHA-256 in `graphrec/auth/api_keys.py` is **at-rest hashing on the
server**, not a signature over the request: `digest_secret` HMACs the presented
secret with a server-side pepper and `hmac.compare_digest`s it against the stored
digest. There is no canonical string, no `X-Signature`, no `X-Timestamp` and no
clock-skew window. An SDK that implemented signing would be implementing
something no server verifies.

The prefix (`gr_live_` + four characters from `[A-Z0-9]`) is a **public
identifier** — it is printed in the console table and in logs. All 256 bits of
entropy are after the `.`. The SDK may log the prefix and must never log
anything after the separator.

### 2.3 Idempotency lives in the body, not in a header

`Idempotency-Key` appears in the control API's CORS `allow_headers`
(`apps/control_api/main.py` line 139) and in the console client's request
options — and **no handler reads it**. Nothing in `apps/` or `graphrec/` calls
`Header(...)` for it. The real mechanism is a field the caller chooses:

- a single event by `event_id`, answered `200` with
  `status: "duplicate_confirmed"` and the original `first_received_at`;
- a collection by `sync_id` or `batch_id`, answered with the original
  submission, unchanged, rather than draining the collection twice;
- a product by `external_id`;
- a recommendation or a feedback batch by `request_id`.

`apps/control_api/routers/ingestion.py` states the rule that makes retries safe:
"a repeat is a **success**: there is no 409 anywhere on this surface, because an
integration retrying after a timeout has done nothing wrong."

The SDK therefore does not send `Idempotency-Key`. It makes the body field
mandatory in the type system instead — see §6.

### 2.4 One error shape, always

Every failure — including a Pydantic 422 and a bare Starlette `HTTPException`,
both translated in `graphrec/http/errors.py` — leaves as:

```json
{"error": {
  "class": "limit", "code": "rate_limited",
  "reason": "Too many requests. Retry in 41 seconds.",
  "reference": "01a0349733be7ad8ba7f69f6507b79fd",
  "field_errors": [], "retryable": false, "retry_after_seconds": 41
}}
```

`class` is one of seven (`validation`, `conflict`, `limit`, `unavailable`,
`auth`, `not_found`, `internal`) and `code` is one of 87 in
`graphrec/common/error_copy.py`. `class`, `reason` and `reference` are a
published contract and will not be renamed; `code` and `field_errors` are
additive. Every response, success or failure, carries `X-Request-Id`, and a
failure's `reference` is the same value.

**403 is class `auth`, not a class of its own.** `ForbiddenError` sets
`error_class = ErrorClass.AUTH` with `status_code = 403`
(`graphrec/common/errors.py` line 174). A client that switches on `class` alone
cannot tell "we do not know who you are" from "we know, and no". Switch on
`status` for that distinction, or on `code`. The console's `errors.ts` declares
a `'forbidden'` member that the server never emits; §12 records it.

### 2.5 TLS 1.3, on both edges

`deploy/n1/Caddyfile` and `deploy/n3/Caddyfile` both pin
`tls { protocols tls1.3 }`. A runtime whose TLS stack cannot negotiate 1.3 fails
the handshake and there is no HTTP status to look up. This is the binding
constraint on the SDK's supported runtimes (§9), and it is sharper on the data
plane, which is called by a customer's server rather than by a browser.

---

## 3. Shape: one client, two transports

**Decision.** A single `GraphRec` object exposing four namespaces — `catalog`,
`events`, `recommendations`, `feedback` — over two internal transports, one per
host. The user constructs one thing and never chooses a host.

**Rejected: two packages** (`@graphrec/control`, `@graphrec/data`). It matches
the deployment exactly, which is its problem: the split is an operational fact
about GraphRec's topology and it would become the customer's problem to hold in
their head. They would also install and version two things that must agree about
the error envelope.

**Rejected: one flat client with a `baseUrl`.** §2.1.

**Failure prevented.** Sending a data-plane call to the control host. With
namespaces bound to transports at construction, that request cannot be
expressed.

---

## 4. Configuration, and the value nobody can look up

```ts
new GraphRec({
  apiKey: process.env.GRAPHREC_API_KEY!,     // gr_live_XXXX.<secret>
  tenantId: process.env.GRAPHREC_TENANT_ID!, // uuid, dashed or hex
  domain: 'graphrec.example',                // -> api.graphrec.example
                                             // -> <hex>.serve.graphrec.example
});
```

`domain` resolves both hosts by the convention in `deploy/`. `controlUrl` and
`dataUrl` override it individually, for a self-hosted estate that names its
hosts differently and for tests pointed at a local stack.

`tenantId` accepts either form and normalises to hex, because the console shows
the dashed UUID and the hostname needs the hex — a customer copying from the
console and pasting into a URL gets a host that does not resolve.

**The uncomfortable part.** No API returns the data-plane hostname.
`GET /v1/tenant` returns `tenant_id`, `tenant_code`, `tenant_name`, `plan_code`,
`status` — and the caller must know to hex the first and know the domain
convention to assemble the rest. `GET /v1/deployment` reports state and replica
counts, not an address. The `/integration` page hardcodes the literal
`https://<your-tenant>.serve.graphrec.example` with a placeholder the customer
is expected to substitute by hand.

The SDK papers over this by deriving the host, which is the right thing for the
SDK and the wrong place to fix it. **The real fix is a `serving_host` field on
`GET /v1/tenant`**, so the address a customer must call is something the server
states rather than something three clients each reconstruct. Recorded in §12;
until it exists, the derivation is the SDK's and is held by a test that reads
`deploy/n3/Caddyfile` (§10).

---

## 5. Errors: one hierarchy, keyed on `code`

```
GraphRecError                     (base; .code .class .reason .reference
                                   .fieldErrors .retryable .retryAfterSeconds
                                   .status .requestId)
├── ValidationError               422 · 413  class=validation
├── ConflictError                 409        class=conflict
├── LimitError                    429        class=limit
│   ├── RateLimitedError                     code=rate_limited
│   └── QuotaExhaustedError                  code=*_quota_exhausted
├── UnavailableError              503        class=unavailable   retryable
├── AuthenticationError           401        class=auth
├── PermissionError               403        class=auth  (scope/role/tenant state)
├── NotFoundError                 404        class=not_found
├── InternalError                 500        class=internal      retryable
└── TransportError                —          (DNS, TLS, connect, read timeout)
```

**Decision.** The subclass is chosen by `status` and `class` together, never by
`class` alone (§2.4). `code` is exposed as a string and is **not** enumerated
into a type. There are 87 codes; freezing them into a union means a server that
adds one produces a value the SDK's own types say is impossible, and the
addition is documented as safe.

**`LimitError` splits, because the two halves need opposite handling.**
`rate_limited` comes from `graphrec/http/rate_limit.py` with a `Retry-After`
computed from the window edge — waiting works. A `*_quota_exhausted` comes from
`graphrec/domain/metering/quota.py` and means the tenant's plan allowance for the
period is spent — waiting for `retry_after_seconds` does not work because there
isn't one, and the remedy is a plan change. Both are `class: "limit"` and both
are `429`. An SDK that collapsed them would retry a quota failure forever.

**`TransportError` has no envelope**, and says so: `reference` is null, because
the request never reached an application that could assign one. This is the
class a TLS 1.3 failure lands in (§2.5), and its message names that possibility
explicitly rather than leaving the caller with `ECONNRESET`.

**`reference` is on every error and the SDK never swallows it.** It is the only
thing a customer can quote to support, and `graphrec/http/errors.py` puts it in
the body and in `X-Request-Id` for exactly that reason.

---

## 6. Retries, and the two questions that decide them

Retrying is only safe when both answers are yes:

1. **Is the failure retryable?** Take the server's word: `error.retryable`.
   `UnavailableError` and `InternalError` set it; `LimitError` sets it only for
   `rate_limited`, and even there the envelope reports `retryable: false` with a
   `retry_after_seconds` — so the SDK treats a present `retry_after_seconds` as
   permission to wait, and `retryable` as permission to back off. A
   `ValidationError` is never retried; the same body will be refused the same way.
2. **Is the call idempotent?** Only if the caller supplied the deduplicating
   identifier. §2.3.

**Decision.** The SDK makes the identifier non-optional in the types for every
route that has one, and defaults it to a fresh UUIDv7 only where the caller
genuinely has no natural key — `request_id` on recommendations. `event_id`,
`sync_id`, `batch_id` and `external_id` are required arguments with no default.

**Rejected: generating all of them.** A generated `batch_id` is different on
every attempt, so the retry the SDK performs on the customer's behalf is a second
submission of the same 5,000 events under a new key. The deduplication the
backend offers would be silently disabled by the convenience the SDK added. If
the caller must think about the key, the caller is the one who knows what it is.

**Policy.** Default `maxRetries: 2` (three attempts), exponential backoff from
250 ms with full jitter, capped at 8 s; `Retry-After` overrides the computed
delay when present. Retries stop at the deadline, not at the attempt count —
`timeout` is a budget for the whole call, so a hot-path recommendation request
with a 200 ms budget does not spend two seconds retrying. Retries are on by
default for `GET` and for the six idempotent `POST`s, and off for everything
else.

**`allow_fallback` is not a retry knob, and the SDK does not touch it.** Setting
it `false` makes a request with no ready model answer `503 model_not_ready`
(`graphrec/domain/serving/recommend.py` line 776) instead of returning a
popularity list. That is a product decision about whether a stale answer is worse
than no answer, it belongs to the caller, and an SDK that flipped it — or retried
past it — would be making it for them.

---

## 7. The typed surface

### 7.1 TypeScript

```ts
const gr = new GraphRec({ apiKey, tenantId, domain });

// data plane — the hot path
const answer = await gr.recommendations.forCustomer({
  requestId: crypto.randomUUID(),
  customerId: 'customer-1',
  topN: 10,
  recentEvents: [{ externalProductId: 'sku-1', eventType: 'view' }],
  excludeProductIds: ['sku-9'],
});
answer.items;              // { externalProductId, rank, score, candidateSource }[]
answer.fallbackApplied;    // true when a popularity list was served
answer.modelVersion;       // null under fallback
answer.latencyMs;

await gr.recommendations.forSession({ requestId, sessionId, topN: 10 });

// data plane — feedback, one call per kind
await gr.feedback.impressions({ requestId: answer.requestId, events: [...] });
await gr.feedback.clicks({ requestId: answer.requestId, events: [...] });
await gr.feedback.conversions({
  requestId: answer.requestId,
  events: [{ eventId: 'order-1', externalProductId: 'sku-1', value: 19.99 }],
});

// control plane — ingestion
const sync = await gr.catalog.bulkUpsert({ syncId: '2026-08-24-nightly',
                                           mode: 'upsert', products });
await gr.events.submit({ eventId, customerId, externalProductId,
                         eventType: 'view', occurredAt });
const batch = await gr.events.submitBatch({ batchId, events });

// control plane — polling a submission to completion
const done = await gr.submissions.wait(sync.submissionId, { timeout: 60_000 });
done.counts;   // { received, accepted, updated, skipped, failed }
done.errors;   // { ref, reason }[]
```

`camelCase` on the surface, `snake_case` on the wire, mapped in one place.
Rejected passing the wire shape through: it is idiomatic in neither language,
and the two spellings would then both appear in customers' code depending on
which layer they touched.

`gr.submissions.wait` is the one place the SDK adds a loop rather than a method.
Bulk upsert and event batches answer `202` with a submission that is `processing`
— every customer writes this poll, and every one of them writes the backoff
slightly wrong. It polls with backoff, resolves on `succeeded`, throws on
`failed` with `errors` attached, and throws a `TimeoutError` carrying the last
observed submission so the caller can keep polling themselves.

### 7.2 Python

The same surface, sync and async from one definition:

```python
gr = GraphRec(api_key=..., tenant_id=..., domain="graphrec.example")
answer = gr.recommendations.for_customer(request_id=..., customer_id="customer-1", top_n=10)

async with AsyncGraphRec(...) as gr:
    answer = await gr.recommendations.for_customer(...)
```

Models are Pydantic v2, which the backend already uses — the request models can
be generated from the same schemas that produced them and enforce the same
bounds client-side (`top_n` ≤ 100, `recent_events` ≤ 50, `exclude_product_ids`
≤ 200, `event_id` ≤ 200 chars). A bound checked locally is a bound the customer
finds at their desk instead of in production.

---

## 8. Generated types, hand-written client

**Decision.** Types are generated from `frontend/openapi.json`; the client is
written by hand.

The repo already does half of this: `frontend/src/api/types.gen.ts` is generated
by openapi-typescript 7.13.0 and `npm run gen:client:check` fails CI when it
drifts from the schema. The SDK's types come from the same document by the same
mechanism, so a schema change is one regeneration and not three transcriptions.

The client is not generated because everything worth having in it is not in the
document: two hosts chosen per operation, the retry policy of §6, the error
hierarchy of §5, the submission poll, the identifier ergonomics. A generated
client produces one flat method per `operationId` with no opinion about any of it.

**A gap this exposes.** The published OpenAPI documents only `200`/`202` and
`422` for all ten routes — no `401`, no `403`, no `404`, no `429`, no `503`, and
no schema for the error envelope at all. A tool that generated a client from this
document would produce one with no typed errors whatsoever, which for the most
important part of a client library is worse than useless. §12.

---

## 9. Runtimes, packaging, versioning

| | Floor | Why |
| --- | --- | --- |
| Node | 20 LTS | `fetch`, `AbortSignal.timeout`, TLS 1.3 |
| Browsers | not supported | see below |
| Python | 3.10 | `httpx`, `X \| None` annotations |

**No browser build, and this is a decision rather than an omission.** The
credential is a bearer token with no origin binding, no expiry by default and
tenant-wide scope; shipping it to a browser puts it in every user's devtools.
The `/integration` page already says "not in the browser". The package declares
no `browser` field and its README says why in the first paragraph, because the
absence of a build is a weaker signal than a sentence.

Distribution: `@graphrec/sdk` on npm (ESM + CJS, `.d.ts`), `graphrec-sdk` on PyPI
(typed, `py.typed`), importable as `graphrec_sdk`. SemVer, where the major tracks
the SDK's own surface and not the API's `/v1` — they are different contracts and
tying them means either a major bump with nothing in it or a breaking change
hidden in a minor.

**Why not `graphrec` on PyPI, which is the obvious name.** This repository
already has a top-level `graphrec/` package — the server — and the SDK's tests
run inside the same `pytest` invocation as the server's. Two importable
`graphrec` packages on one `sys.path` is a collision that resolves silently to
whichever came first, and the failure mode is a test importing half of each. The
distribution can still be *called* `graphrec-sdk` and the import name has to
differ from the server's, so it does. A customer never sees the server package,
but the people maintaining both do, and the name is chosen for them.

Every request sends `User-Agent: graphrec-{lang}/{version}` and accepts a
caller-supplied `X-Request-Id`, which `graphrec/http/middleware.py` echoes and
truncates to 64 characters — so a customer's own trace id survives into GraphRec's
logs and into the `reference` on any error, which is what makes a support
conversation about a specific request possible.

---

## 10. What holds it

This repo's convention (ADR 0049) is that a document asserting something about
the system is held by a test that fails in both directions. The SDK is held the
same way, and the tests below are part of the deliverable rather than a follow-up.

1. **The route table matches the schema.** Every method the SDK exposes maps to a
   path, method and host that exist in `frontend/openapi.json`, and every
   operation whose `servers[0]` is either public host has a method. Fails when
   the API adds a public route the SDK has not covered, which is the drift that
   otherwise gets found by a customer.
2. **The host derivation matches the deploy.** A test reads
   `deploy/n3/Caddyfile`, extracts the `labels.N` index and the upstream template,
   and asserts the SDK's `dataUrl` produces a hostname that resolves to
   `graphrec-serve-{hex}-inference`. This is the assertion that catches §4's
   convention being changed under the SDK.
3. **The error mapping is total.** Every `class`/`status` pair the backend can
   emit maps to exactly one exception, driven by `ErrorClass` and `DEFAULT_STATUS`
   from `graphrec/common/errors.py` plus the `status_code` overrides. Fails when a
   class is added.
4. **`retryable` is honoured and quota is not retried.** A fake transport
   returning `429 rate_limited` with `Retry-After` is retried; one returning
   `429 recommendation_quota_exhausted` is not, and the test asserts the request
   count is exactly one.
5. **A retry sends the same identifier.** Two attempts of one `submitBatch`
   carry the same `batch_id`. This is the test that would have caught the
   convenience rejected in §6.
6. **Nothing after the separator is ever logged or serialised.** The SDK's
   client and error types are stringified with a credential in them and the
   output is asserted not to contain the secret — the same defence
   `GeneratedSecret.__repr__` provides on the server, on the grounds that this
   failure is silent and so belongs on the type rather than in discipline.
7. **The examples in the README execute.** Against a recorded transport, so a
   copy-pasted snippet compiles and its types are the shipped types.

A contract test in the backend repo asserts (1) and (3) from the other side, so
the two cannot drift while both suites pass.

---

## 11. Build order

1. Transport, config and host derivation; error hierarchy; tests 2, 3, 6.
2. Data plane — recommendations and the three feedback calls. This is the hot
   path and the reason the SDK exists; a customer can integrate against it before
   anything else lands.
3. Retry and timeout budget; tests 4 and 5.
4. Control plane — bulk upsert, events, batches, submissions, and the poll.
5. Python, from the same schemas.
6. README, examples, test 7.

Steps 1–3 are the release worth shipping first. A customer who can only call
`/v1/recommendations` still has the thing they bought.

---

## 12. Defects found while writing this

These are real, they are in customer-facing paths, and they are listed here
rather than fixed silently in an SDK design.

1. **`/integration` documents the wrong credential prefix.**
   `frontend/src/routes/integration/Integration.tsx` line 258 shows
   `Authorization: Bearer grk_live_…`. The prefix is `gr_live_`
   (`PREFIX_NAMESPACE`, `graphrec/auth/api_keys.py` line 41). This is on the one
   page a customer copies their first request from. `Credentials.test.tsx` uses
   `grk_live_` fixtures too, which is why no test caught it — the fixture agrees
   with the bug.
2. **The published OpenAPI documents no error responses.** All ten public
   routes list only their success status and `422`. The envelope has no schema in
   `components`. §8.
3. **No API returns the data-plane hostname.** Every client reconstructs it from
   `tenant_id` plus a domain convention. A `serving_host` field on
   `GET /v1/tenant` would end that. §4.
4. **`Idempotency-Key` is accepted by CORS and read by nothing.** Either the
   header should be honoured or it should come out of `allow_headers` and out of
   the console client's comment; as it stands it invites an integration to rely on
   a mechanism that does not exist. §2.3.
5. **`deploy/n3/Caddyfile` calls the credential "an HMAC over the request".** It
   is a bearer token; the HMAC is at-rest. The conclusion the comment draws — that
   Caddy cannot route on it — is still correct, for a better reason: routing on a
   credential would require the verification the application exists to do.
6. **`frontend/src/api/errors.ts` declares `'forbidden'` as an `ErrorClass`.**
   The server has seven classes and that is not one of them; a 403 arrives as
   `class: "auth"`. Any console code branching on `'forbidden'` is dead. §2.4.
7. **Two public routes are missing from `/integration`.**
   `GET /v1/events/batches/{batch_id}` and `POST /v1/recommendations/session`. §1.
8. **`/integration` names the wrong scope for `GET /v1/submissions/{submission_id}`.**
   The page says `events:write` (`Integration.tsx` line 109). The route depends on
   `ReadSubmissions`, which is `require_ingest(CredentialScope.SUBMISSIONS_READ)`
   (`apps/control_api/routers/ingestion.py` lines 55 and 240). A customer who
   follows the page and mints a credential with `catalog:write` and `events:write`
   can submit a batch and then gets `403 insufficient_scope` on the only route
   that tells them how it went. `Integration.test.tsx` checks every row against
   `openapi.json`, and `openapi.json` carries `HTTPBearer` with an empty scope
   array for every operation — so the scope column of that table is held by
   nothing, which is why this and (1) both survived.

---

## 13. Open questions

- **Does a `gr_test_` lane exist?** `api_keys.py` line 39 says the environment
  segment "is fixed at `live` because this system has one" and that a test lane
  "would be a product decision". Without one, a customer's staging environment
  uses production credentials against production data, and the SDK has no
  sandbox to point at. This is the largest gap in the integration story and it is
  not an SDK decision.
- **Are the data-plane routes rate limited at all?** The five configured classes
  are `login`, `registration`, `api_key`, `usage`, `subscription` — all console
  concerns. `/v1/recommendations` appears to be bounded by quota only. If that is
  intended, §6's backoff on the hot path is for quota and transport alone; if it
  is an omission, the SDK's retry policy should be revisited when it is closed.
- **What is the `Retry-After` on a quota refusal?** `LimitError` carries one only
  when the caller passes it, and `quota.py` passes `resets_on` as copy rather than
  as a number. The SDK cannot compute a wait from a sentence.

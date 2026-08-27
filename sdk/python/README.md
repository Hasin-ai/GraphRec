# `graphrec-sdk`

A client for the GraphRec API, for **Python 3.10 or newer, on your server**.

<!-- example: importing -->
```python
from graphrec_sdk import GraphRec
```

The distribution is `graphrec-sdk` and the import is `graphrec_sdk`. Not
`graphrec`: this repository already has a top-level `graphrec/` package — the
server — and two importable `graphrec` packages on one `sys.path` resolve
silently to whichever came first.

## It does not run in a browser, and that is not an oversight

Every call carries a `gr_live_` credential, and that credential is a bearer
token: whoever holds it can read one tenant's catalogue, write its events and
spend its quota. There is no public-key variant, no origin restriction and no
per-session scope-down that would make it safe to send to a browser — including
via a page that calls this SDK through a thin proxy that forwards everything.

The shape that works is the ordinary one: your browser talks to your server,
your server holds the credential and calls GraphRec. That also puts your own
identity check in front of every recommendation, which is the check GraphRec
cannot make for you.

**Both GraphRec edges require TLS 1.3.** A runtime pinned to an old OpenSSL
fails the handshake, and a handshake failure has no HTTP status to look up.

## Install

```sh
pip install graphrec-sdk
```

## Two hosts, one client

GraphRec answers on two hostnames. The **control plane** — catalogue, events,
submissions — is one host shared by every tenant. The **data plane** —
recommendations and feedback — is a host **per tenant**, because N3's edge
resolves your replicas from the subdomain rather than from the path or the
credential. A single base URL cannot express that, so the SDK takes your domain
and derives both:

<!-- example: construct -->
```python
import os

from graphrec_sdk import GraphRec

gr = GraphRec(
    api_key=os.environ["GRAPHREC_API_KEY"],
    tenant_id=os.environ["GRAPHREC_TENANT_ID"],
    domain="graphrec.example",
)
```

That yields `https://api.graphrec.example` and
`https://<tenant-hex>.serve.graphrec.example`. If your estate parameterises the
two independently — it can; they are `GRAPHREC_CONSOLE_DOMAIN` and
`GRAPHREC_API_DOMAIN` — pass `console_domain` and `api_domain`, or `control_url`
and `data_url` to override the origins outright.

The tenant id may be dashed as the console prints it or bare hex as the hostname
needs it. Nothing in the surface lets a call choose its host.

## Async

`AsyncGraphRec` has the same constructor, the same namespaces and the same
method names, with `async def` throughout. `tests/sdk/test_surface.py` asserts
the two are signature-for-signature identical, so a method added to one and not
the other fails the suite.

<!-- example: asynchronous -->
```python
from graphrec_sdk import AsyncGraphRec

async with AsyncGraphRec(
    api_key=os.environ["GRAPHREC_API_KEY"],
    tenant_id=os.environ["GRAPHREC_TENANT_ID"],
    domain="graphrec.example",
) as gr:
    answer = await gr.recommendations.for_customer(
        request_id=str(uuid.uuid4()), customer_id="customer-1"
    )
```

The client owns a connection pool, so construct it once for the process rather
than once per request, and close it — `async with`, or `await gr.aclose()`.

## Recommendations

<!-- example: recommend -->
```python
import uuid

answer = gr.recommendations.for_customer(
    request_id=str(uuid.uuid4()),
    customer_id="customer-1",
    top_n=10,
    recent_events=[{"external_product_id": "sku-1", "event_type": "view"}],
    exclude_product_ids=["sku-9"],
)

for item in answer.items:
    print(item.rank, item.external_product_id, item.score)
```

`for_session` is the same call for a visitor you have no customer id for.

## Feedback

<!-- example: report -->
```python
gr.feedback.impressions(
    request_id=answer.request_id,
    events=[
        {
            "event_id": f"{answer.request_id}:{item.external_product_id}",
            "external_product_id": item.external_product_id,
        }
        for item in answer.items
    ],
)

gr.feedback.conversions(
    request_id=answer.request_id,
    events=[{"event_id": "order-4471", "external_product_id": "sku-1", "value": 19.99}],
)
```


## Catalogue and events

A bulk upsert is accepted, not applied — it returns a submission you poll.

<!-- example: sync -->
```python
accepted = gr.catalog.sync(
    sync_id="2026-08-24-nightly",
    products=[{"external_id": "sku-1", "title": "Example product", "price": "19.99"}],
)
finished = gr.submissions.wait(accepted.submission_id, timeout=120)
print(finished.counts)
```

`mode="upsert_and_disable_missing"` disables every product **not** in the
request. On a full catalogue that is what you want; on one page of a paginated
export it empties the shop, and the SDK cannot tell the two apart.

<!-- example: ingest -->
```python
from datetime import datetime, timezone

receipt = gr.events.submit(
    event_id="11111111-1111-4111-8111-111111111111",
    customer_id="customer-1",
    external_product_id="sku-1",
    event_type="view",
    occurred_at=datetime.now(timezone.utc),
)
```

`occurred_at` must carry a timezone. A naive `datetime` is refused rather than
assumed to be UTC, because "2026-08-14 09:41" is a different instant in
different places and guessing would silently reorder a tenant's event history.

`value` on an ingestion event is a decimal **string** (or a `Decimal`) because it
is money; `value` on a feedback event is a **float** because it is a ranking
signal. The two planes model it differently on purpose and the SDK does not
paper over it.

## Idempotency

**The SDK never invents an identifier.** `event_id`, `sync_id`, `batch_id` and
`request_id` are yours, and a repeat carrying the same one is deduplicated by
the server and answered with a success rather than a 409. A generated id would
be a different id on every attempt, which would turn the SDK's own retry into a
second write.

`Idempotency-Key` is not used: it appears in the API's CORS allowlist and no
handler reads it. The key is in the body.

## Errors

Every failure is a `GraphRecError` subclass carrying `code`, `reason`,
`reference` (your `X-Request-Id`, echoed) and `field_errors`.

| Class | Status | Meaning |
| --- | --- | --- |
| `ValidationError` | 422 | The request is malformed. `field_errors` says where. |
| `ConflictError` | 409 | The state does not permit it. |
| `RateLimitedError` | 429 | Too fast. Carries `retry_after_seconds`. |
| `QuotaExhaustedError` | 429 | Allowance spent. **Waiting does not help.** |
| `AuthenticationError` | 401, 403 | Bad credential, or one without the scope. |
| `NotFoundError` | 404 | No such thing, for this tenant. |
| `UnavailableError` | 503 | Transient. Retried automatically. |
| `InternalError` | 500 | Ours. Retried automatically. |
| `APITimeoutError` | — | Your budget elapsed. |
| `TransportError` | — | The connection failed. Check TLS 1.3. |

Two names differ from the TypeScript SDK because Python has builtins of those
names: `APITimeoutError` (not `TimeoutError`) and `PermissionDeniedError` (not
`PermissionError`). `from graphrec_sdk import TimeoutError` would otherwise
change the meaning of `except TimeoutError` in code with nothing to do with this
SDK.

`PermissionDeniedError` subclasses `AuthenticationError`, because the API reports
403 with `"class": "auth"` and the SDK keeps that shape rather than inventing a
class the server never sends.

<!-- example: handle -->
```python
from graphrec_sdk import QuotaExhaustedError, RateLimitedError, RecommendationResponse

def recommend_or_fall_back(customer_id: str) -> RecommendationResponse | None:
    try:
        return gr.recommendations.for_customer(
            request_id=str(uuid.uuid4()), customer_id=customer_id
        )
    except QuotaExhaustedError:
        return None  # Waiting will not help: the allowance resets with the period.
    except RateLimitedError:
        return None  # The SDK already retried inside your timeout budget.
```

Returning `None` and rendering the shop's own ordering is the shape that belongs
in a hot path. A recommendation is an enhancement, and a page that fails because
the enhancement did is worse than a page without it.

A submission that finishes in `failed` raises only from `wait`; `submissions.get`
returns it as a value, because a failed submission is an answer.

<!-- example: failed -->
```python
from graphrec_sdk import SubmissionFailedError

def sync_and_report(sync_id: str, products: list[dict]) -> list[str]:
    accepted = gr.catalog.sync(sync_id=sync_id, products=products)
    try:
        gr.submissions.wait(accepted.submission_id)
    except SubmissionFailedError as failure:
        return [f"{item.ref}: {item.reason}" for item in failure.submission.errors]
    return []
```

`SubmissionTimeoutError` is the other outcome: the submission is still running,
and the exception carries the last state polled so a caller can decide whether
to keep waiting or come back later.

A bound checked locally raises the same `ValidationError` the server would, with
`reference=None` because no request was made. Pydantic's own `ValidationError`
never escapes this package.

## Retries and the timeout budget

`timeout` is a budget for the **whole call**, retries included, in **seconds** —
this is Python. It defaults to 10. `max_retries` defaults to 2. An attempt is
retried only when the call is idempotent, the server said the condition was
transient (`retryable`, or a named `retry_after_seconds`), and the next attempt
fits in the remaining budget.

Backoff is exponential with full jitter from 250 ms, capped at 8 s, except when
the server named a wait. A `QuotaExhaustedError` reports neither, so it is
attempted exactly once.

## The credential

The secret is held behind name mangling on a `__slots__` class with no
`__dict__`, and `__repr__`, `__str__` and `__reduce__` are all overridden — so
it is absent from `repr()`, from `logging`'s `extra`, from `pprint`, and from
`pickle`. `gr.credential_prefix` stays visible, because a support conversation
needs to name a key without quoting it.

## Scopes

| Namespace | Scope |
| --- | --- |
| `catalog` | `catalog:write` |
| `events` | `events:write` |
| `submissions` | `submissions:read` |
| `recommendations` | `recommendations:read` |
| `feedback` | `feedback:write` |

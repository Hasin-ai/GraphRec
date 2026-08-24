# ADR 0047 — The published OpenAPI is the merge of both planes

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

§24: *"OpenAPI published and matching `/integration`'s documented shapes"*.

There are two FastAPI applications. `apps/control_api` answers on N1 — the
console, the catalogue, ingestion, the platform realm. `apps/inference` answers
on N3 — recommendations and feedback, routed by hostname, one process per
tenant. Each generates its own document.

`scripts/gen_openapi.py` built the control app and published that. It was 67
paths and it was missing the entire data plane: `POST /v1/recommendations`, the
one call every customer makes, was not in the published document at all. The
`/integration` page — the page that tells a customer how to integrate — was
checked against that document, so the check was passing over a document that did
not contain the endpoints the page exists to describe.

Three options. Publish two documents, and make every reader work out which one
answers a given call. Publish the control document and describe the data plane
in prose, which is what had happened by accident. Or merge.

## Decision

**One document, merged from both applications, with every operation naming the
server that answers it.**

```json
"servers": [{"url": "https://{tenant}.{api_domain}", …}]
```

Two server templates: `https://{console_domain}` for N1, and
`https://{tenant}.{api_domain}` for N3 — the tenant is a *path variable of the
hostname*, because N3 routes on the hostname and never on the path or the
credential. An operation carries one of them at the operation level, not the
document level, so a generated client sends each call to the host that answers
it rather than to a single base URL that is right half the time.

Merging is refused rather than resolved where it is ambiguous. A path present in
both applications raises `SystemExit`. A schema name present in both with
*different* definitions raises `SystemExit`; present in both and identical, it is
shared. Only the transitive `$ref` closure of the operations that survive is
carried, so the inference app's `RecommendationRequestBody` comes along and its
differing `HealthResponse` does not.

The inference app is built for generation with `tenant_id` set to the nil UUID —
it names no tenant and reaches nothing.

Two tests hold it. `tests/contract/test_openapi_document.py` asserts both planes
are present and that the committed file is byte-for-byte what the generator
produces today, with the message *"run `python scripts/gen_openapi.py`"*.
`frontend/src/routes/integration/Integration.test.tsx` checks every row of the
page against the document — path, method, host, request fields, response fields.

## Consequences

Generation now needs both applications importable in one process, so a change
that makes the inference app depend on something the control app cannot import
breaks the build of the document. The import-linter contracts already forbid the
apps importing each other, which is what keeps that from happening quietly.

`OPERATIONAL = {"/healthz", "/readyz"}` is filtered out of the merge — both
applications define them, with different bodies, and neither is part of the
published contract.

The byte-for-byte test means a FastAPI upgrade that changes generated JSON at
all turns into a red build with an instruction. That is louder than necessary
for a cosmetic change and is the correct default: the alternative is a published
document that drifts from the server one release at a time.

The two-host check earned its place immediately. It found the `/integration`
page documenting `POST /v1/recommendations/feedback`, a route that has never
existed — the real ones are `/v1/feedback/{impressions,clicks,conversions}` —
along with a recommendation response example that did not match
`RecommendationResponse` in four fields.

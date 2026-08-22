# Phase 5 — Catalog

**Status:** complete.
**Suite:** 435 passed, 0 failed (`.venv/bin/pytest`), of which 94 are new.
**Lint / types:** `ruff format`, `ruff check`, `mypy graphrec apps` all clean.
**Gates:** D9 and D10 — recorded as ADR 0012 and ADR 0013, *confirmed by
instruction to proceed*. See §5.

BUILD_PROMPT's bar for this phase: *"`/products*` endpoints are complete and the
eligibility function returns identical results from both call sites."* Both are
met; the second is §2's first entry.

---

## 1. What was built

### Migration — `migrations/versions/0007_catalog.py`

`product_categories` and `products`, and one function.

The function is the phase. Eligibility is derived, never stored
(BACKEND_PLAN §3.5), and the derivation is written **once, in SQL**:

```sql
CREATE FUNCTION product_ineligibility(is_active, availability, deleted_at)
RETURNS text IMMUTABLE PARALLEL SAFE CALLED ON NULL INPUT
```

It returns the *reason* — `product_removed`, `product_inactive`,
`product_out_of_stock` — rather than a boolean, and that choice is what lets
three call sites be one expression:

* `ix_products_eligible ON products (tenant_id) WHERE product_ineligibility(...) IS NULL`,
  the partial index the serving path walks;
* the serving path's own `WHERE`, which must match that index for the planner to
  use it;
* the API's `served` / `ineligible` badge **and** the sentence under the title
  (dc.html L1302, L1307), which needs to know *which* reason applies.

A boolean would have forced a second rule somewhere to decide the wording, and
that second rule is what drifts.

The function is deliberately **not** `STRICT`. `deleted_at` is NULL for every
live product, and a strict function returns NULL for a NULL argument — which
reads as "eligible" by accident rather than by decision, and would make the
index predicate `NULL IS NULL`, i.e. every row.

Other pins in 0007: RLS `ENABLE` + `FORCE` + `USING` + `WITH CHECK` on both
tables; `GRANT SELECT, INSERT, UPDATE` to `graphrec_app` and **no `DELETE`**,
because L1339–L1340 makes removal a state, not a disappearance; **no platform
grant at all**, because the platform realm renders seven tables and `products`
is not one of them; `EXECUTE` on the function revoked from `PUBLIC`.

### `graphrec/db/models/catalog.py`

`Product` and `ProductCategory`. `Product.ineligibility` is a hybrid: a Python
branch for an instance already loaded, and a SQL branch that **calls the
database function** rather than re-implementing it. `__repr__` returns the id
alone — no title, no price (NR-NF-06).

### `graphrec/catalog/eligibility.py`

Only what SQL cannot hold: the wording for each reason. `"Out of stock —
excluded from serving"` and `"Inactive — excluded from serving"` are verbatim
from dc.html L683/L686. `exclusion_reason(None)` returns `None`, not `""`,
because L1302 is `sub: p.eligible ? '' : p.why`.

### `graphrec/domain/catalog/service.py`

`CatalogService` with `create`, `upsert`, `patch`, `disable`, `get`,
`list_products` and `eligible_ids` — the last being the serving path's call
site, written now so that the two call sites exist and can be compared.

### `graphrec/domain/quotas.py`

Effective-limit resolution: active override → standing tenant quota → plan
limit, with `PLAN_LIMIT_COLUMN` mapping each `UsageType` to its plan column.
Written as the general answer rather than a product-shaped special case, because
Phase 7 is its second caller and a second implementation is how the console
comes to quote a number the enforcement does not use.

### `apps/control_api/routers/products.py` + schemas

Six routes under `/v1/products`, all **developer-only** — see §3.

### Error copy

`product_already_exists` corrected, and three field/banner pairs unswapped — §3.

---

## 2. What was verified, and how

| Exit criterion | Where |
|---|---|
| The eligibility rule agrees across every call site | `tests/catalog/test_eligibility.py` |
| `/products*` complete | `tests/catalog/test_products_api.py` |
| Quota enforced before the write | `test_the_quota_is_enforced_before_the_insert` |
| Tenant isolation on every verb | `tests/catalog/test_service.py` |

**The exit criterion, in detail.** There are four spellings of the eligibility
rule — the SQL function, the hybrid's Python branch, the hybrid's SQL branch,
and the partial index predicate — and `test_eligibility.py` evaluates all of
them over the **entire input space**: 2 × 3 × 2 = 12 combinations, enumerated,
not sampled. They are measured against a fifth statement of the rule written out
longhand from BACKEND_PLAN §3.5, so no implementation is ever compared with
itself.

The index is checked separately, with `SET LOCAL enable_seqscan = off`, by
asserting `ix_products_eligible` appears in the plan for the serving query. An
index whose predicate is merely *equivalent-looking* to the filter would not be
chosen, and the serving path would seq-scan the catalogue — correct, and
unusable at 250,000 products.

**Properties pinned by tests:**

* A foreign product is `404`, and the reason names no resource type.
* An unbound session sees **zero** products, not all of them.
* `WITH CHECK` refuses an insert stamped with another tenant's id.
* A `PUT` from tenant B against tenant A's external id creates B's own product
  and leaves A's untouched — the lookup carries no tenant predicate, so this
  test fails loudly if RLS ever stops carrying the scope.
* Two tenants may hold the same external identifier.
* A category is created on first reference and is not shared across tenants.
* `PUT` resets omitted fields; `PATCH` leaves them; `PATCH {"brand": null}`
  clears. All three, separately.
* `PUT` answers `201` then `200`.
* A disabled product still counts against the quota — otherwise the limit is
  evadable while the catalogue stays exactly as large as it was.
* Disabling is `404` before it is `409` for a product that does not exist —
  gate 4 before gate 5.
* Prices cross the wire as strings (`"8.40"`).
* A search for `50%` finds the product called "50% off", not the whole
  catalogue.
* `repr(Product)` carries neither title nor price.
* An administrator is `403` on **all six** routes, reads included.

---

## 3. Defects found and fixed

**1. `product_categories.created_at` / `updated_at` were nullable.** Caught by
the existing `tests/isolation/test_model_schema_parity.py`, not by anything
written this phase. A `server_default` without `nullable=False` leaves the
column optional, so an explicit NULL would have given a category no creation
time. Fixed in 0007 and the migration re-run end to end (`downgrade 0006` then
`upgrade head`) to confirm the round trip still works.

**2. `product_already_exists` carried `API.md`'s paraphrase.** The catalogue
held *"a product with identifier … already exists"*. The prototype renders *"A
product with identifier SKU-4471 already exists. **Use a different identifier or
update the existing product.**"* (L1604). `API.md` is not binding
(BUILD_PROMPT §0); the prototype is. The dropped sentence is the half that tells
the tenant what to do next. Corrected, and `tests/api/test_error_envelope.py`
updated — it had pinned the paraphrase.

**3. Three field/banner error strings were in the wrong slots.** The prototype
splits a field failure in two: `err({body:'An external product identifier is
required.'}, {id:'Required.'})` at L1602 puts the sentence in the banner and a
short marker beside the input. `FIELD_ERROR_COPY` held the banner sentence for
`external_id_required`, `title_required` and `business_name_required`, which
would have rendered the same sentence twice on one screen. Both halves are now
present, in the right slots, and the parity test asserts both against the same
prototype line — which is what catches a swap.

**4. `ValidationError("email_required")` would have raised `MissingErrorCopy`.**
A latent Phase 2 bug: `graphrec/domain/identity/service.py:453` raises a code
that existed only in `FIELD_ERROR_COPY`, so resolving its reason would have
thrown and turned a 422 into a 500. Nothing tested it. Fixed by adding the
banner entries, which the same L1234/L1581/L1602/L1605 transcription supplied.

**5. `CatalogService.list` shadowed the builtin.** With
`from __future__ import annotations`, mypy resolves every `list[...]` annotation
in the class body against class scope, where `list` was the method. Renamed
`list_products`, with a comment saying why.

---

## 4. Departures and what was **not** done

**The `/products*` routes are session-only.** No credential-realm access, so
`catalog:write` has no live call site yet. This is not an oversight: the
integration page documents exactly one catalogue endpoint,
`POST /v1/products:bulk-upsert` (L1173), and that is Phase 6's. Adding
credential auth to the console's CRUD routes now would be inventing a surface
the specification does not describe.

**Optimistic concurrency is copy without a mechanism.** L1335's *"A concurrent
change to the same product is reported as a state conflict; your entries are
kept so you can reconcile them"* is in the catalogue as
`product_concurrent_change`, and **nothing raises it**. `products` has no
version column and the writes are last-writer-wins. This is the largest gap in
the phase and it is deliberate: adding a version column is cheap, but deciding
*where* the version travels — an `If-Match` header, a body field, or the
`updated_at` the console already renders — is an interface decision that touches
Phase 6's bulk path too, and guessing it here would mean changing it there. It
is flagged in ADR 0012 §Consequences and belongs in Phase 6's scope.

**No cursor pagination was built.** ADR 0013 decides both mechanisms; the cursor
half has no caller until Phase 6's submission errors. Building the encoder
before the first consumer means guessing what it must encode.

**`:disable` writes no audit row.** The dialog says the reason "is written to the
audit history" (L1340). The reason is persisted on the product
(`disabled_reason`, `disabled_at`) but `audit_logs` gets no entry, because the
audit-write helper does not exist yet — Phase 12 owns it. The data needed to
backfill is on the row.

**`_assert_product_quota` admits a one-row overshoot.** Under `READ COMMITTED`
two concurrent creates can both pass the boundary at 49,999. Accepted
deliberately and documented in the function: serialising every catalogue write
behind a lock to prevent a one-product overshoot on a 50,000-product limit costs
far more than it saves.

**Category names are the tenant's own strings.** The prototype offers a fixed
select (Hardware / Timber / Power tools / Workwear, L1322), which is fixture
data, not a vocabulary. Categories are created on first reference, since the
console has no category-management screen and a sync carries names inline.

---

## 5. Decisions recorded

**ADR 0012 — Products take three write verbs (D9).** `POST` + `PUT` + `PATCH`.
Decided by two facts pointing in opposite directions: L1604's conflict is a
sentence only a create can produce, while L1320 calls the external identifier
"the idempotency key for later updates" and an integration that retries must not
get a `409`. `PATCH` exists because the detail form (L1337) carries five of the
product's fields and not the description, so a `PUT` there would blank it on
every save.

**ADR 0013 — Offset for consoles, cursors for volume (D10).** The console
renders "8 of 12" (L1316) and a cursor cannot produce the second number; a deep
export cannot use `OFFSET 900000`. Both, distinguished by endpoint rather than
by a parameter, so no caller has to choose.

Both are marked *confirmed by instruction to proceed* rather than by a separate
answer to the gate. That is a weaker confirmation than an explicit one and is
named as such in `docs/adr/README.md` rather than dressed up. Both remain cheap
to revisit: D9 adds or removes a verb on one resource, D10 a parameter on a
list.

---

## 6. Open items requiring a human

1. **The concurrency conflict** (§4). Needs a decision on where the version
   travels before Phase 6 writes the bulk path.
2. **CI has still never executed.** The workflow exists; no run has happened, so
   `GRAPHREC_REQUIRE_DB=1` has never actually been exercised in CI.
3. **The local Docker stack is still broken** — carried from Phase 4. Needs
   `POSTGRES_PORT=5442`, `REDIS_PORT=6389`, `S3_PORT=9010`,
   `S3_CONSOLE_PORT=9011` in `.env` plus an image rebuild; `graphrec-postgres-1`
   currently binds host 5432 and clashes with the native instance the tests use.
4. **Qdrant** (SRS §6.3 vs D4) still needs an explicit "defer" before Phase 10.
5. **Retention** — how long raw interaction events are kept, and what tenant
   deletion erases — is unanswered and now blocks nothing until Phase 6.

---

## 7. Phase 6

Ingestion. BUILD_PROMPT marks **no confirmation gate** on it. It adds
`customers`, `interaction_events`, `submissions` and `submission_errors`;
`POST /v1/events` with `duplicate_confirmed`; the two `202` bulk paths
(`/v1/events/batches`, `/v1/products:bulk-upsert`) with streaming
bounded-memory validation, a staging table and a single merge transaction;
capped error samples; and the unified `GET /v1/submissions/{id}`. It registers
`EVENT_BATCH` and `PRODUCT_BULK_UPSERT` into the Phase 4 worker, and it is the
first caller of both the credential realm's `catalog:write` scope and ADR 0013's
cursor half.

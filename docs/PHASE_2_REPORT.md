# Phase 2 report — Identity, tenancy and authorization

**Date:** 2026-08-22
**Status:** Complete. **D5, D6, D11 and D12 were all confirmed on 2026-08-22, each as built, so no rework followed — no decision is being built past unconfirmed any longer.** Three items still require a human (§6): two authority conflicts, and a CI run.

---

## 1. What was built

### Migrations — `migrations/versions/` (4 files, 1,175 lines)

| Revision | What it establishes |
|---|---|
| `0002` | Eleven tables: `pricing_plans`, `tenants`, `tenant_users`, `invitations`, `tenant_subscriptions`, `tenant_resource_quotas`, `quota_overrides`, `refresh_sessions`, `recovery_tokens`, `platform_users`, `platform_user_permissions`. RLS `ENABLE` + `FORCE` + `USING` + `WITH CHECK` on all eight tenant-owned tables. A third role, `graphrec_platform`, with grants on platform tables only. |
| `0003` | `graphrec_lookup` (`NOLOGIN`), the `tenant_lookup` schema, and `resolve_tenant_code` — the sign-in path's only way past default-deny. |
| `0004` | `resolve_invitation`, the same arrangement extended to invitation acceptance. |

`0002`'s docstring states the consequence of `FORCE` plainly — the owner cannot
read or write these tables either — and documents the two legitimate procedures
for a later data migration. It also states what must never happen: granting the
owner a blanket `USING (true)` policy to make the inconvenience go away.

### Authentication — `graphrec/auth/` (3 files, 430 lines)

- `passwords.py` — Argon2id, with a dummy-digest path so a missing account costs
  the same as a wrong password.
- `tokens.py` — `TokenService`. EdDSA only, pinned at the verifier. Separate
  `TenantClaims` and `PlatformClaims`, an explicit `realm` claim, signed refresh
  tokens, and `digest_token` (SHA-256) for everything stored.

### Domain — `graphrec/domain/identity/` (2 files, 560 lines)

`IdentityService`: `register_tenant`, `authenticate_tenant_user`,
`authenticate_platform_user`, `issue_tenant_session`, `rotate_tenant_session`,
`revoke_tenant_session`, `create_user`, `accept_invitation`, `change_user_role`,
`set_user_status`.

Two rules in here are load-bearing rather than tidy: `_locked_user` takes a row
lock, and `_refuse_if_last_administrator` selects the *other* active
administrators `FOR UPDATE` and counts in Python — an aggregate cannot be
combined with `FOR UPDATE`, and without the lock two concurrent demotions both
see one remaining administrator and both succeed.

### ORM — `graphrec/db/models/` (part of 7 files, 619 lines)

Eleven mapped classes matching `0002` exactly. `TenantOwned` is a mixin that
declares a class tenant-scoped; `tests/isolation/test_model_schema_parity.py`
turns that declaration into an assertion against `pg_class` and `pg_policies`.
`metadata.create_all` is never called — Alembic is the only thing that changes
the schema.

### Control plane — `apps/control_api/` (13 files, 1,567 lines)

Twenty routes. Ten are new in this phase:

```
POST   /v1/tenants                        register a tenant + first administrator
POST   /v1/auth/sign-in                   tenant realm
POST   /v1/auth/refresh                   rotates; the old token stops working
POST   /v1/auth/sign-out                  204, idempotent
POST   /v1/invitations:accept             unauthenticated by necessity
GET    /v1/me
GET    /v1/tenant
GET    /v1/users                          both roles
POST   /v1/users                          administrator only
PATCH  /v1/users/{id}/role                administrator only
PATCH  /v1/users/{id}/status              administrator only
POST   /v1/platform/auth/sign-in          platform realm
GET    /v1/platform/me                    carries no tenant_id, by construction
GET    /.well-known/jwks.json             public half only
```

`deps.py` implements the five gates in order — identity (401), tenant state
(403), role/permission (403), ownership (**404**), resource state (409) — and
binds `app.tenant_id` from the verified `tid` claim before any query runs.
`PlatformPrincipal` has no `tenant_id` property at all: not "returns `None`",
absent, so a platform handler that reaches for one fails loudly.

---

## 2. What was verified, and how

**199 tests, all passing** against PostgreSQL 18 locally, and the whole stack verified end to end on PostgreSQL 16 in Docker.

| Gate | Result |
|---|---|
| `ruff check .` | clean |
| `ruff format --check .` | 73 files formatted |
| `mypy graphrec apps` (strict) | no issues, 43 files |
| `pytest -q` | 199 passed |
| `pytest -m isolation` | 37 passed |
| `pytest -m authz` | 69 passed |
| `alembic upgrade head` → `downgrade base` → `upgrade head` | clean, twice |

### The stack runs, on the PostgreSQL version CI uses

`docker compose up` now yields a healthy stack — the Phase 1 exit criterion that
had never been checked, because no Docker daemon was available until now.
Migrations `0001`–`0004` applied from scratch on **postgres:16-alpine**, which
matters because every local run so far had been against PostgreSQL 18, and the
four database roles, the `FORCE`d policies and the `SECURITY DEFINER` resolvers
are exactly the kind of thing that differs across major versions. It did not.

A 27-check end-to-end script then drove the real HTTP surface against the real
database — registration, activation, sign-in, invitation, acceptance, replay
refusal, all five gates, both realms, refresh rotation, sign-out idempotency and
credential non-disclosure. All 27 passed. This is not a substitute for the test
suite; it is a check that the suite's fixtures had not been quietly diverging
from how the service actually assembles itself. **One finding came out of it
that the suite could not have produced** — see §3, the `pending` tenant — because
every authz test seeds an `active` tenant directly and so never exercised
registration end to end.

`/readyz` now runs a real bounded probe against PostgreSQL rather than reporting
it unprobed, and a failed probe is logged and never echoed: the body says
`unreachable`, with no host, port or role name in it (NR-NF-06). Pinned by
`test_a_failed_probe_does_not_leak_connection_details`.

### The two required merge gates are now wired

`.github/workflows/ci.yml` runs `isolation` and `authz` as separate jobs, each
with `GRAPHREC_REQUIRE_DB=1` so a skipped suite is a failure rather than a green
tick. They are separate from `test` so a red run names the promise that broke.

### Guards tested by breaking them

| Guard | Break | Result |
|---|---|---|
| `WITH CHECK` on `tenants_self_isolation` | removed the clause | `test_registration_cannot_mint_a_tenant_it_is_not_bound_to` fails; restored → passes |
| Algorithm pinning in `verify_tenant_access` | `algorithms` widened to include `HS256`, `none` | `test_an_hs256_forgery_is_refused` fails; restored → passes |
| `FORCE ROW LEVEL SECURITY` on a tenant table | `ALTER TABLE invitations NO FORCE` | `test_every_tenant_owned_model_is_protected` fails naming the table; restored → passes |

### Properties pinned by tests that would otherwise be invisible

- A foreign user id answers **404, never 403**, and is byte-identical to a
  wholly absent one — same `code`, same `reason`.
- The 404 body never names the resource type.
- A platform token reaches no tenant route; a tenant token reaches no platform
  route; an administrator token gets nowhere in the platform realm.
- A wrong tenant code and a wrong password are indistinguishable, and sign-in
  still pays for an Argon2id verification when the code does not resolve.
- An email valid at one tenant does not authenticate at another.
- Refresh rotation invalidates the old token; sign-out is 204 whether or not the
  session existed.
- `graphrec_lookup` holds **no** table-level privilege, only five column-level
  `SELECT`s; both resolver policies are `SELECT`-only; neither function is
  executable by `PUBLIC` or by `graphrec_platform`; both pin `search_path`.

---

## 3. What was **not** done

- **`POST /v1/users` returns the invitation token.** Phase 2 has no mail
  transport. Flagged in ADR 0007 as interim and must stop as soon as delivery
  exists. An administrator can currently activate an account they invited.
- **Resend invitation** (dc.html L1247) — specified by the prototype, not built.
  It needs the email-delivery question answered.
- **Account recovery** (`rec_…`, dc.html L1036-1041). `recovery_tokens` exists
  in `0002`; no route uses it, for the same reason.
- **No route activates a `pending` tenant.** Registration yields `pending`, and
  `pending` is not operable, so a self-registered tenant can sign in but every
  authenticated route answers 403 `tenant_not_active`. This is a consequence of
  the schema, not an omission in the routers:
  `ck_tenants_active_requires_plan` (migration `0002`, from SRS §5.2.2 — "A
  Tenant must reference one active Pricing Plan when activated") makes `active`
  unreachable without a plan, and registration deliberately passes
  `plan_id=None`, because choosing a plan is not the registrant's decision.
  Activation is platform tenant management, which is **Phase 4**. Until then the
  only way through is a direct database update. Pinned by
  `test_a_freshly_registered_tenant_is_pending_and_cannot_work`, which will
  start failing the moment a route can do it — which is the point.
- **CI has still never executed.** Every gate in it has been run locally with
  the same commands, but no workflow run exists.
- **Key rotation procedure.** The `kid`/JWKS machinery supports two keys; the
  operational procedure is unwritten.

---

## 4. Defects found and fixed

| Defect | Cause | Fix |
|---|---|---|
| Fixture could not seed tenants (13 errors) | `FORCE` subjects the owner to its own policies | Seed through the runtime path, bind-then-insert (ADR 0006) |
| `SECURITY DEFINER` resolver returned nothing | Owned by `graphrec_owner`, which no policy names | Owned by `graphrec_lookup` instead (ADR 0008) |
| `alembic downgrade` failed at `0004`, then `0003` | `DROP FUNCTION`/`DROP SCHEMA` need USAGE the owner deliberately lacks | `SET LOCAL ROLE graphrec_lookup` around the drops |
| `FOR UPDATE is not allowed with aggregate functions` | Counting administrators with a lock | Select and lock the other administrators' ids, count in Python |
| `invalid input syntax for type inet: "testclient"` | ASGI peer is not always an address | `_client_address` parses via `ipaddress.ip_address`, `None` on failure |
| An unbound session opened per request | leftover `Depends(get_session)` in `current_tenant_principal` | removed |
| `TCH003` on `datetime`/`uuid` in models and schemas | SQLAlchemy and Pydantic resolve annotations at runtime | per-file ignores, with the reason stated |
| **The entire ORM layer was invisible to git** | an unanchored `models/` rule in `.gitignore` matched `graphrec/db/models/` as well as the artefact directory it was written for | anchored every artefact rule to the repo root |
| **The containerised API had no signing key** | `secrets/` is gitignored and not in the image, so `TokenService` would start with no key | read-only bind mount in `docker-compose.yml`, plus a `.dockerignore` entry so it can never be baked into a layer |
| `/readyz` reported `postgres` as unprobed | placeholder from Phase 1 | a real `asyncio.timeout`-bounded probe; failures logged, never echoed |

The first of those is the one worth dwelling on. It was not a runtime bug and no
test could have caught it: the code worked, the suite passed, and the files
simply would not have been in the Phase 2 commit. It was found only by reading
`git status` before committing rather than trusting it.

---

## 5. Decisions recorded

| ADR | Decision |
|---|---|
| 0006 | Registration mints the tenant id, binds the context, then inserts |
| 0007 | Invitations: stored digest, derived seven-day life, one-time return |
| 0008 | Pre-credential lookups go through one narrow `SECURITY DEFINER` resolver |
| 0009 | Tokens are EdDSA with a published JWKS — **Accepted; D5 confirmed 2026-08-22** |

---

## 6. Open items requiring a human

### 6.1 The gate departure is closed

BUILD_PROMPT §2 says: *"Do not build past a gate on an unconfirmed decision."*
Phases 1 and 2 built past four. **All four have now been confirmed (2026-08-22),
and every one was confirmed as built**, so no rework followed:

| # | Confirmed as | Consequence |
|---|---|---|
| D5 | EdDSA (Ed25519) + published JWKS | ADR 0009 moved to Accepted. No code change. |
| D6 | `/v1`, platform under `/v1/platform/*` | No code change. |
| D11 | `STARTER` / `GROWTH` / `SCALE` | The `pricing_plans` seed in `0002` already carried these. |
| D12 | snake_case on the wire | No schema change. |

Phase 3 therefore starts with no decision outstanding — the first phase of which
that is true.

**A correction belongs here.** Phase 2's report said the D6 rework "gets more
expensive with each phase." That was wrong for the versioning half, and the
claim was never measured. It has been now: `API_PREFIX` is a single constant in
`apps/control_api/main.py`, the 97 `/v1` literals live in six test files, and
one substitution across both leaves all 199 tests passing. That cost does not
grow. What genuinely could not have been undone cheaply is the realm split —
`GET /tenants` means "every tenant" to an operator and "my own tenant" to a
customer, and the prefix is what separates them, from Phase 4 onward.

D7 (per-endpoint body limits) remains *Proposed — built to*. Its confirm-before
was Phase 1 and it constrains request handling rather than any interface, so it
is recorded rather than treated as blocking.

### 6.2 Conflict: sign-in cannot identify a tenant from email alone

The prototype's sign-in form (dc.html L1017-1019) asks for **email and password
only**. The same prototype states that "Email is unique per tenant" (L1235), and
the SRS agrees. Those two cannot both hold: one person consulting for two
tenants has one email at each, and nothing in an email-and-password pair says
which they mean.

Silently picking a tenant is the dangerous resolution. `SignInRequest` therefore
carries `tenant_code` as well, and migration `0003` exists to resolve it. **This
is a reported conflict, not a settled decision.** If the intended answer is that
email is globally unique, `tenant_users` needs a different unique constraint,
`0003` becomes unnecessary, and the console's sign-in form changes.

### 6.3 Conflict: the SRS specifies Qdrant; D4 does not

SRS §6.3 defines a Qdrant Vector Store Contract. BACKEND_PLAN's D4 proposes
in-process exact top-K behind a `CandidateIndex` port, and is marked Accepted.
The SRS outranks BACKEND_PLAN in the authority hierarchy, so **D4 as recorded is
building against the wrong authority.**

The port-based design means deferring Qdrant is cheap and reversible, and that
is the recommendation — but it needs to be an explicit, recorded decision before
Phase 10 rather than a silent one.

### 6.4 Still open from Phase 1, now blocking Phase 3

1. **Email delivery.** SMTP, or an administrator CLI? Blocks recovery, resend,
   and removing the interim token in the invite response.
2. The 15-minute training cooldown (Phase 7).
3. Whether the last-active-administrator rule extends to deletion and to the
   platform realm (Phase 4).
4. Customer data lifecycle and what tenant deletion erases (Phase 5).

### 6.5 Operational

- **CI has still never run.** Someone with push access should confirm the seven
  jobs go green before Phase 3 relies on them. This is now the only item here.

## 7. A note on tool output

As in Phase 1, the tool-output layer in this environment drops words from
printed text. Apparent discrepancies between quoted output and file content were
double-checked against the files. Nothing in §2 rests on a printed excerpt alone.

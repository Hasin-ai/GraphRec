# Phase 3 report — Credentials

**Date:** 2026-08-22
**Status:** Complete. All three of BUILD_PROMPT's exit criteria are met and
pinned by tests, with **one deliberate departure from the letter of the first
one, made on your instruction** (§3.1). Two items require a human (§6), both
carried forward from Phase 2.

---

## 1. What was built

### Migration — `migrations/versions/0005_api_keys.py` (223 lines)

One table, `api_keys`, and the third pre-credential resolver.

The interesting parts are the absences. **No `DELETE` grant to any runtime
role** — BUILD_PROMPT states this verbatim, and revocation is `revoked_at`
rather than removal, because a credential that submitted events is part of the
audit trail and a row that can be deleted is a row that can be deleted to hide
something. **No `key_hash` in the lookup role's grant** — the resolver holds
column-level `SELECT` on exactly `tenant_id`, `visible_prefix` and
`previous_visible_prefix`.

RLS `ENABLE` + `FORCE` + `USING` + `WITH CHECK`, as every tenant-owned table
gets. Three policies: tenant isolation for `graphrec_app` (`ALL`), a read-only
policy for `graphrec_platform`, and a read-only policy for `graphrec_lookup`.

Three `CHECK` constraints: name length 1–100, scope cardinality 1–12 (a
credential with no scope authorizes nothing, and the API is not the only way
rows arrive), and `ck_api_keys_previous_is_all_or_nothing` — the four `previous_*`
columns move together or not at all. A half-populated predecessor would be a
credential that could be looked up but not verified, or verified against a
digest with no expiry, which is a permanent second live secret.

### Secret generation — `graphrec/auth/api_keys.py` (160 lines)

`HMAC-SHA-256(pepper, secret)` with a versioned server-side pepper. This is the
deliberate opposite of the password module next door, and the difference is not
arbitrary: a password is low-entropy and human-chosen and needs a slow KDF; a
credential secret is 256 bits from `secrets.token_bytes`, has no guessing
surface, and is verified on **every authenticated request**. Argon2id there
would add latency to the hot path and buy nothing. SRS §5.2.4 and BACKEND_PLAN
§17 both specify HMAC here.

A pepper rather than a per-row salt, for the same reason: salts defend against
precomputation, which does not apply to a 256-bit random value. What a pepper
defends against is the stolen database *alone*. `hash_version` records which
pepper produced each digest, so a pepper can be replaced without invalidating
every credential in the estate at once.

`hmac.compare_digest` on every path including the failing ones, plus
`dummy_verify` so an unknown prefix costs the same as a wrong secret. Without
that, the API is a timing oracle for which prefixes exist.

`GeneratedSecret.__repr__` is deliberately lossy. A dataclass repr would put the
secret into every stack trace, log line and debugger frame that touched it —
exactly what NR-NF-06 forbids — and that failure is silent, so the defence
belongs on the type rather than in the discipline of each call site.

### Domain — `graphrec/domain/credentials/` (395 lines)

`CredentialService`: `create`, `rotate`, `revoke`, `get`, `list_for_tenant`,
`verify`.

`verify` is the one to read carefully. It runs **before any tenant context
exists**, because a credential is how the caller proves which tenant they are.
That makes it structurally the same problem as sign-in, and it gets the same
answer (ADR 0008): resolve the prefix to one identifier through a narrow
`SECURITY DEFINER` function, bind the context to *that* identifier, and only then
read any tenant-owned row. The tenant is never taken from a header, a path or a
body — `verify(session, *, presented)` has no parameter through which one could
be suggested, which a test asserts by reading the signature.

Two orderings inside it are load-bearing:

- **State is checked after the secret, not before.** Checking first would let a
  caller learn that a prefix names a revoked credential without holding the
  secret for it.
- **Every refusal is the same `invalid_credentials`.** Distinguishing "no such
  prefix" from "wrong secret" from "revoked" hands an attacker a classifier.

### Realm and gates — `apps/control_api/deps.py`

A third realm: `CredentialPrincipal`, carrying `tenant_id` and **scopes instead
of a role**. There is deliberately no `role` property and no `is_administrator`.
A role says which screens a person may open; a scope says which operations a
program may perform, and a handler written for the session realm must not be
able to accept a credential and silently treat it as an administrator.

`require_scope(*scopes)` requires **all** the named scopes, not any — a route
declaring two is stating it performs two kinds of operation, and "any of" would
let a read-only credential reach a route that also writes.

`refuse_scope_delegation` is the containment property: a credential may never
issue authority it does not itself hold. Without it, a credential holding only
`events:write` could mint one holding `recommendations:read`, and every scope in
the system would be advisory.

### Routes — `apps/control_api/routers/api_keys.py` (210 lines)

`GET /v1/scopes`, and `GET`/`POST`/`GET {id}`/`POST {id}:rotate`/`DELETE {id}`
under `/v1/api-keys`.

All six are **session-authenticated only**. No credential can reach them, which
makes the scope-delegation refusal structural rather than conditional: there is
no code path here that inspects a credential's scopes and decides, because no
credential arrives.

`state`, `can_rotate`, `can_revoke` and `blocked_reason` are computed on the
server, so the console disables a control and shows *the server's* reason. The
prototype does this client-side at L1118–1119; a real client must not, for the
same reason it must not derive `state` — it does not own the clock or the rules.

Both tenant roles may manage credentials (dc.html L1258 lists it as true for
both), which is the one capability the two roles share. A developer who cannot
issue a credential cannot integrate anything.

---

## 2. What was verified, and how

**256 tests pass** — 42 isolation, 122 authz, 63 contract, the rest unit and
integration. Up from 199 at the end of Phase 2. `ruff check` clean,
`ruff format --check` clean, `mypy graphrec apps` clean on 48 source files under
`strict`.

**The migration round-trips on the real thing.** `alembic downgrade 0004` then
`upgrade head` against `postgres:16-alpine` in Docker, followed by a direct
probe of the result: `relrowsecurity` and `relforcerowsecurity` both `t`; three
policies present with the expected commands and roles; three resolvers in
`tenant_lookup`; and the grant list on `api_keys` showing `graphrec_app` with
`SELECT, INSERT, UPDATE` and **no `DELETE` to any role but the owner**.

**Two isolation tests failed when this phase's migration landed, and that was
the system working.** `test_the_lookup_role_holds_only_column_level_selects` and
`test_the_lookup_policies_are_select_only` assert *exact* sets, so a new hole in
default-deny cannot be absorbed silently — it has to be declared. Both were
updated to name the `api_keys` grant and policy explicitly, with the reason
`key_hash` is excluded written next to the list.

**One new test was found to be passing vacuously, and was rewritten.** The
assertion that the lookup role cannot read a digest was first written against
`information_schema.column_privileges`, which only shows grants to roles the
*caller* is a member of. `graphrec_app` is a member of nothing — that is the
point of it — so the view returned an empty set and the assertion would have
passed against any grant whatsoever, including a table-wide one. It now reads
`pg_catalog.pg_attribute` through `aclexplode`, and sees the three columns.

**One test was flaky by construction and was fixed.** A "wrong secret" built by
flipping the last character lands back on the original whenever that character
was already the replacement — roughly one run in 64, and it failed on the
first. It now substitutes the whole tail.

### Properties pinned by tests that would otherwise be invisible

| Property | Test |
|---|---|
| The secret appears in no column of the stored row, not even its random half | `test_the_secret_appears_in_no_column_of_the_row` |
| No read route ever returns a secret | `test_no_read_route_ever_returns_the_secret` |
| `repr` never renders a secret | `test_the_issued_credential_never_renders_its_secret` |
| The predecessor verifies during grace and reports `used_grace_secret` | `test_the_predecessor_still_verifies_during_grace` |
| …and stops the moment the window lapses | `test_the_predecessor_stops_the_moment_the_window_lapses` |
| Two rotations never leave three live secrets | `test_a_second_rotation_does_not_extend_the_first_window` |
| Revocation kills an open grace window too | `test_revoking_during_grace_kills_the_predecessor_too` |
| A grace secret carries current scopes, not the ones it was minted with | `test_the_predecessor_keeps_the_scopes_it_was_rotated_into` |
| Unknown prefix and wrong secret are indistinguishable | `test_an_unknown_prefix_and_a_wrong_secret_say_the_same_thing` |
| A credential resolves only to its own tenant | `test_a_credential_only_ever_resolves_to_its_own_tenant` |
| An unbound `SELECT` on `api_keys` returns nothing | `test_a_credential_is_unreadable_without_a_bound_context` |
| The lookup role cannot reach `key_hash` | `test_the_resolver_cannot_be_made_to_return_a_digest` |
| No role may `DELETE` a credential | `test_no_role_may_delete_a_credential` |
| A foreign credential is 404, never 403 | `test_another_tenants_credential_is_404_and_never_403` |
| Scopes mean all-of, not any-of | `test_two_declared_scopes_mean_all_of_them_not_any_of_them` |
| A `CredentialPrincipal` has no `role` | `test_a_credential_principal_has_no_role` |
| A session token is not a credential | `test_a_session_token_is_not_a_credential` |
| A rejected scope string is never echoed back | `test_an_unrecognized_scope_is_refused_without_echoing_it` |

---

## 3. Departures and what was **not** done

### 3.1 "Exactly once" is implemented as **twice in a credential's life**

BUILD_PROMPT's Phase 3 exit criterion says the secret is *"returned exactly
once."* Taken literally that is unsatisfiable alongside the same phase's
requirement for rotation, since a rotation that returned no secret would produce
a credential nobody could use.

Read as *once per issuance event*, the two agree: a secret is returned at
creation and at rotation, and at no other moment in the credential's life. **You
confirmed this reading on 2026-08-22** ("use twice in a key's life method"), and
it is what shipped. There are exactly two routes that return a secret, no read
route that does, and no column that could serve one.

### 3.2 The credential realm has no live route yet

`current_credential_principal` and `require_scope` exist and are tested, but
nothing on the request path consumes them: the credential-management routes are
session-only by design, and the first route that *accepts* a credential is
`POST /v1/events` in Phase 6.

This is inherent to the phase order rather than an omission, but it is worth
stating plainly: **the verification path is exercised by tests, not yet by
traffic.** The tests call `CredentialService.verify` directly for that reason,
and they were written now rather than alongside their first caller because a
guard introduced at the same time as the route it guards is a guard nobody
reviews.

### 3.3 `last_used_at` is written on every verification

The column is documented as coarse and the intent is to throttle it to at most
one write per credential per minute, so the authentication hot path is not also
a write path. **The throttle is not implemented**; it lands with the rate
limiter in Phase 7. At present every authenticated request would dirty one row.
Harmless at Phase 3 traffic — which is zero — and a real cost later.

### 3.4 Not yet done, by design

- **Pepper rotation.** `hash_version` is stored and honoured, and a digest
  remains verifiable by the pepper that produced it. There is no re-hash-on-use
  path and no procedure document. The machinery is present; the operation is not.
- **Credential audit events.** Creation, rotation and revocation are not yet
  written to `audit_logs` — that table arrives with the platform realm.
- **`GET /v1/api-keys?state=` filters in Python**, after loading the tenant's
  rows, because `state` is derived from the clock rather than stored. Correct,
  and fine at a cap of 25 credentials per tenant; it would not be at 25,000.

---

## 4. Defects found and fixed

| Defect | Cause | Fix |
|---|---|---|
| 18 credential tests errored at fixture setup with `invalid_credentials` | `GRAPHREC_POSTGRES_*` exported at the container database while the fixtures seed the local one | migrated the local database; dropped the overrides |
| Prototype validation copy replaced by Pydantic's generic wording | `min_length` on `name`/`scopes` rejects before the service runs, yielding "List should have at least 1 item" instead of the strings at dc.html L1136/L1137 | removed `min_length`; emptiness checks live in the service where the catalogue is reachable. `max_length` stays — an abuse limit, not product copy |
| `MissingErrorCopy` on `credential_name_required` | code raised before it was catalogued | added with the prototype's L1136 string |
| Two isolation tests failed on the new migration | exact-set assertions on the lookup role's grants and policies | declared the new hole rather than loosening the assertion |
| A privilege assertion passed vacuously | `information_schema` hides grants to roles the caller is not a member of | re-read through `pg_catalog.pg_attribute` + `aclexplode` |
| A "wrong secret" test was flaky at ~1 run in 64 | single-character mutation can land on the original | substitute the whole tail |
| `TCH002`/`TCH003` in the service | `uuid` and `AsyncSession` are annotation-only | moved into `if TYPE_CHECKING` rather than adding a per-file ignore |

The vacuous assertion is the one worth dwelling on. It passed on the first run,
against code that was in fact correct, and it would have gone on passing if a
later migration had granted the lookup role every column in the table. A test
that cannot fail is worse than no test, because it is counted.

---

## 5. Decisions recorded

| ADR | Decision |
|---|---|
| 0010 | Rotation grace is opt-in and defaults to none |

ADR 0010 resolves a genuine conflict between two authorities. The prototype's
rotate dialog states (L1145) that *"requests still using the old secret will
fail authentication"*; BUILD_PROMPT requires rotate-with-grace, and `.env`
already carries `MAX_API_KEY_GRACE_SECONDS=86400`.

Both are right about their own realm. The prototype describes what a person
clicking that button gets; BUILD_PROMPT describes what a fleet mid-deploy needs.
`grace_seconds` therefore defaults to `0` and is opt-in, so every console-driven
rotation makes the prototype's copy **literally** true, while an API caller can
request a bounded window. Out-of-range values are refused rather than clamped:
silently shortening a window an integrator asked for would cut them off at a
moment they did not choose, which is the failure the window exists to prevent.

---

## 6. Open items requiring a human

Both are carried forward from Phase 2 unchanged.

### 6.1 CI has still never executed

Seven jobs are defined; `isolation` and `authz` are meant to be required checks
from Phase 2 onward. Nothing has run, because nothing has been pushed. Until it
does, "the required merge gate passes" is a claim about a local machine.

### 6.2 Email delivery

Still unanswered, and it now blocks slightly more than it did: account recovery,
resend-invitation (dc.html L1247), and removing the interim `invitation_token`
from the invitation response.

### 6.3 Unchanged conflicts

The SRS specifies a Qdrant Vector Store Contract (§6.3), which outranks D4's
in-process exact top-K. An explicit "defer Qdrant" decision is needed before
Phase 10 — not now, but the decision does not get cheaper.

---

## 7. Phase 4 gate

BUILD_PROMPT marks Phase 4 with 🛑 **CONFIRM D2 (PostgreSQL queue) before
starting.** D2 is currently *Accepted* in the ADR index on BACKEND_PLAN's
authority rather than confirmed by you, and its stated confirm-before is Phase
5. Phase 4 is the job system, which *is* the queue, so this is the decision the
phase consists of.

**Phase 4 is not started.** Confirming D2 — jobs claimed from a PostgreSQL table
with `FOR UPDATE SKIP LOCKED`, rather than a dedicated broker — is what unblocks
it.

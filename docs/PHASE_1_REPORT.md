# Phase 1 report — Foundation

**Date:** 2026-08-22
**Status:** Complete. **Phase 2 is blocked pending confirmation of D1.**

---

## 1. What was built

### Shared library — `graphrec/common/` (14 files, 1,341 lines)

| Module | Purpose |
|---|---|
| `config.py` | The whole §22.4 configuration surface. Every user-facing bound is a named setting (§13.22), never a literal. Two startup validators: production refuses to start carrying a shipped default secret, and the bulk body limit must exceed the default. |
| `errors.py` | `ErrorClass` (7 values), `DEFAULT_STATUS`, `FieldError`, `ErrorBody` serialising `error_class` as the wire name `class`, and `GraphRecError` carrying a `code` rather than a message. |
| `error_copy.py` | ~60 approved sentences, each citing the `dc.html` line it came from. A missing code raises `MissingErrorCopy` and is fatal by design. |
| `logging.py` | Structured JSON logging; `ContextVar`s for request / tenant / actor / job; redaction of sensitive keys and of value-shaped secrets (`gr_live_…`, `Bearer …`, `eyJ…`). |
| `clock.py` | Injectable `Clock` protocol and `FrozenClock`, so no code path reaches for `datetime.now()` directly. |
| `ids.py` | UUIDv7 (PostgreSQL 16 has none of its own) and `new_request_reference()` in the console's `err-3f81-7a20c` shape. |
| `enums.py` | **Generated.** Do not hand-edit. |

### Control plane — `apps/` (11 files, 514 lines)

`create_app()`, raw-ASGI request-context middleware, per-endpoint body limits,
the four exception handlers, and `/healthz` / `/readyz`. `/v1` exists and is
empty, awaiting Phase 2. `redirect_slashes=False`, because a 307 to a different
path drops the `Authorization` header on some clients.

### Migrations (2 files, 248 lines)

`0001` establishes the privilege separation everything else assumes: extensions,
the `graphrec_app` runtime role, `USAGE` but not `CREATE` on `public`, sequence
default privileges — and **no default table grants at all**.

### Generators and tooling (2 files, 740 lines)

- `scripts/gen_enums.py` — parses the prototype and emits both
  `graphrec/common/enums.py` and `frontend/src/lib/enums.ts`, with `--check` for
  CI and pinned vocabularies (ADR 0003).
- `scripts/gen_jwt_keys.py` — Ed25519 keypair and JWKS document. Writes the
  private key `0600` via `os.open`, not `chmod` afterwards, and refuses to
  overwrite an existing key without `--force`.

### Project infrastructure

`pyproject.toml` (ruff, mypy strict, pytest markers, import-linter contracts),
`docker-compose.yml`, `Dockerfile` (non-root), `.env.example`, `.gitignore`,
`.github/workflows/ci.yml` (6 jobs), `README.md`, and this `docs/adr/` set.

---

## 2. What was verified, and how

**97 tests collected: 90 pass, 7 skip without a database.** With a database, 97 pass.

| Gate | Result |
|---|---|
| `ruff check .` | clean |
| `ruff format --check .` | 43 files formatted |
| `mypy graphrec apps` (strict) | no issues, 25 files |
| `lint-imports` | 3 contracts kept, 0 broken |
| `gen_enums.py --check` | parity holds |
| `pytest` | 90 passed, 7 skipped |
| `pytest -m isolation` (with DB) | 7 passed |

### Verified against a real PostgreSQL 18

Docker's daemon was unavailable, so migrations were exercised against a local
PostgreSQL 18 in a throwaway database, which was dropped afterwards. This turned
out to be more informative than a Compose run would have been, because it used a
**non-superuser** migration owner — the configuration the design actually
requires — and that is what exposed the two defects in §4.

- `alembic upgrade head` → `downgrade base` → `upgrade head`. The re-apply is the
  case that actually breaks, since `CREATE ROLE` has no `IF NOT EXISTS`.
- After upgrade: `graphrec_app` is `super=false, bypassrls=false, createrole=false,
  login=true, inherit=false`; extensions `pgcrypto` and `pg_trgm` present;
  `USAGE = true`, `CREATE = false`; and connecting as `graphrec_app` and running
  `CREATE TABLE` returns `permission denied for schema public`.
- After downgrade: privileges revoked, extensions dropped, `alembic_version` empty.

### Guards tested by breaking them

A guard that has never fired is a guess. Each was tested against deliberate
sabotage:

| Guard | Scenarios | Detected |
|---|---|---|
| Enum drift (`gen_enums.py --check`) | 7 (added / removed / **renamed** value, dropped stage, **reordered** stage rail, changed scope, changed permission) | **7 / 7** |
| Isolation gate | 4 (grant `BYPASSRLS`; grant `CREATE` on `public`; add a default table grant; unreachable DB under `GRAPHREC_REQUIRE_DB=1`) | **4 / 4** |
| Migration privilege guard | 2 (owner without `CREATEROLE`; runtime role holding `BYPASSRLS` + `CREATEDB`) | **2 / 2** |
| Error-copy parity | 40 line-cited entries (33 verbatim, 7 templated) | all asserted |

The enum guard originally caught only 3 of 5 scenarios. A **renamed** badge value
and a **dropped** job stage regenerated silently, because the check compared the
two artefacts to each other rather than to the specification. ADR 0003 records
the fix.

---

## 3. What was **not** done

Stated plainly, because a report naming its gaps is more useful than one that
omits them.

1. **`docker compose up` was never run.** The Docker daemon is not running on this
   machine. The Compose file, Dockerfile and healthchecks are written but
   **unexecuted**. Migrations and the API were verified by other means; the
   container build, the MinIO service and the service dependency ordering were
   not. This is the largest untested surface in Phase 1.
2. **CI has never executed.** The workflow is syntactically valid and every step's
   command was run locally, but no push has triggered it. The `services:` blocks
   and the frontend job's `hashFiles` guard are unverified.
3. **No commit exists.** See §6.
4. **`/readyz` probes nothing.** It reports all three dependencies as
   `unavailable` with a reason, deliberately, rather than falsely reporting
   `pass`. Real probes arrive with the connection pools in Phase 2.
5. **No `authz` or `db` tests beyond the isolation set.** There is nothing yet to
   authorise. The markers and the CI gate exist so that adding the first test
   does not also require someone to remember to add the gate.
6. **`frontend/` is a directory with a generated `enums.ts` and nothing else.**
   Scaffolding begins at Phase 12.

---

## 4. Defects found and fixed

Two were in code already written; two were in this phase's own work.

1. **`DO $$ … $$` cannot carry bind parameters.** Migration `0001` created the
   runtime role inside a `DO` block with a bound password. A `DO` body is an opaque
   string to the server, so the parameter has no resolvable type; psycopg failed
   with `IndeterminateDatatype`. Interpolating the password into the string instead
   would have put a secret one quote away from SQL injection. Now an ordinary
   parameterised existence check plus a statement composed with `psycopg.sql`.
   *Found only by running the migration against a real server.*

2. **`ALTER ROLE … NOSUPERUSER NOBYPASSRLS` cannot work.** PostgreSQL only lets a
   role change an attribute it holds itself, so the statement fails on exactly the
   deployments the design requires and succeeds only when migrations run as a
   superuser — the configuration being avoided. The attributes are now **verified**
   and the migration fails with an actionable message. See ADR 0002.

3. **The log redactor broke every `%`-formatted third-party log line.**
   `ContextFilter` tested `key in logging.LogRecord.__dict__`, which is the *class*
   dictionary of methods, not a record's instance attributes. `record.args` was
   therefore redacted and returned as a list; `LogRecord.getMessage` does
   `msg % args`, and `%` treats a tuple as an argument list but a list as a single
   value, so every httpx / uvicorn / SQLAlchemy line raised `TypeError`. See
   ADR 0005.

4. **A test asserted a framework behaviour that was never occurring.** The
   Pydantic-422 test defined its request model *inside* the test function. The
   module carries `from __future__ import annotations`, so FastAPI received the
   annotation as the string `"Body"` and resolved it against module globals, where
   a function-local class does not exist. It silently demoted the parameter to a
   **query** scalar, producing `loc = ('query', 'body')`. The envelope was correct
   throughout; the test was exercising the wrong code path. The model now lives at
   module scope with a comment explaining why. A second test was added asserting
   that a framework 422 never echoes Pydantic's `input` field, which would
   otherwise relay a rejected password straight back to the caller.

---

## 5. Decisions recorded

| ADR | Subject | Status |
|---|---|---|
| 0001 | Per-endpoint body limits (D7) | **Proposed — built to** |
| 0002 | Runtime-role attributes verified, not assigned; no default table grants | Accepted |
| 0003 | Generated vocabularies are pinned, not merely regenerated | Accepted |
| 0004 | Errors carry a code; the sentence comes from a line-cited catalogue | Accepted |
| 0005 | Request context is raw ASGI; the redactor must never change a type | Accepted |

---

## 6. Open items requiring a human

### Blocking: the CONFIRM gates

BUILD_PROMPT §2: *"Do not build past a gate on an unconfirmed decision."* Phase 1
was built entirely on D1-independent foundations, which is why it could proceed.
Phase 2 cannot.

**D1 — the resource model — must be answered before any schema work.** The
appendix is explicit: *"Ask the D1 question. Do not write code until it is
answered."* It determines the shape of every table, every route and every console
URL, and BUILD_PROMPT names retrofitting `tenant_id` and RLS "the single most
expensive mistake available in this project".

Also unconfirmed and due before Phase 2 or 3: **D5** (EdDSA + JWKS), **D6**
(`/v1` and `/v1/platform/*`), **D11** (STARTER / GROWTH / SCALE), **D12**
(snake_case), and **D7**, which was built to its recommendation but never
confirmed. `docs/adr/README.md` carries the full table, plus the four open
questions that have no recommendation at all: email delivery, the 15-minute
training cooldown, the last-active-administrator rule, and the customer data
lifecycle.

### Operational

A zero-byte `.git/index.lock`, dated 01:55, is blocking all commits. Cursor's
`gitWorker.js` helper is running but no `git` process holds the lock. **No commit
has been made in this repository yet** — the entire specification set and all of
Phase 1 are untracked. I have not removed the lock unilaterally. To clear it:

```
rm .git/index.lock
```

Then the baseline commit of the specification documents and Phase 1 can be made.

### A note on tool output

The output-compression layer in this session drops words from printed text — for
example rendering `"Correct the highlighted field and submit again."` as
`"Correct highlighted field submit again."`. The underlying strings were verified
correct by direct assertion. Apparent copy discrepancies in transcript output
should be checked against the file before being treated as real drift.

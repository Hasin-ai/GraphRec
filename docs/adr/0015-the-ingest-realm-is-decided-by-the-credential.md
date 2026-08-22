# ADR 0015 — The ingest realm is decided by the credential presented, never by the caller

**Status:** Accepted
**Phase:** 6
**Gate:** none.

## Context

The ingest routes are the first place where two authentication realms meet on
one path. The prototype's /integration page documents `POST /v1/events` as
something an integration calls with an API key (L1173-L1180); the console's own
Submit event form calls the same endpoint with the developer's session. Both are
real callers and both must reach the same handler, because a second endpoint
would be a second implementation of the same validation.

BUILD_PROMPT's constraint is absolute: *"Tenant identity comes only from the
verified credential. Never from a path, query or body parameter."* So the realm
cannot be selected by a header the caller chooses, a query flag, or a body
field — any of those is a caller-supplied input deciding which verifier runs.

## Decision

`require_ingest(*scopes, roles=...)` in `apps/control_api/deps.py` reads the
bearer token and dispatches on its **shape**: a secret beginning with
`PREFIX_NAMESPACE` (`gr_live_`) goes to the credential verifier, anything else
goes to the session verifier. The namespace is a property of a secret this
platform minted, not a claim the caller makes about itself.

This is a *routing* decision only. It selects which verifier runs; that verifier
still has to succeed. A forged `gr_live_...` string reaches the credential path
and fails there, exactly as it would have failed anywhere else. Nothing about
tenancy is decided by the dispatch.

Gate 3 is then applied **in whichever realm answered, by that realm's own
vocabulary**, and the two are not mapped onto each other:

* a **session** is judged by **role**, because the prototype marks every ingest
  screen `[DEV]` and L1256 states an administrator has *"No catalog access and
  no event submission"*;
* a **credential** is judged by **scope**, because a program holds operations
  rather than a job title.

Collapsing these — treating an administrator's session as holding
`events:write`, or a credential as holding a role — would describe a grant the
tenant never made. A credential therefore never receives `insufficient_role`
and a session never receives `insufficient_scope`; the refusal a caller gets
names the thing that caller actually has.

Both realms are entered through `contextlib.asynccontextmanager` wrappers over
the existing principal dependencies and delegated to with `async with`, so
exactly one place in the codebase turns a token into a tenant. An `async for`
over the raw generator would leave the inner generator suspended at its `yield`
inside an open transaction, waiting for a garbage collector to decide the
tenant's data's fate.

## Consequences

* Changing the credential prefix is a breaking change to route dispatch as well
  as to verification. `PREFIX_NAMESPACE` is the single definition of it.
* Routes outside ingestion keep their single-realm dependencies. A credential
  presented to `/v1/users` is refused, because that route asks for a session and
  a credential is not one — the dual realm is opt-in per route, not ambient.
* `IngestPrincipal.realm` records which realm answered. It is attribution for
  audit and logging; nothing authorizes off it.

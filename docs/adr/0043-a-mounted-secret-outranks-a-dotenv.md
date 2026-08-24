# ADR 0043 — A mounted secret outranks a `.env`

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

§24: *"Secrets from files or a store; none in images, Compose literals or Git."*
Compose mounts a secret at `/run/secrets/<name>`, and pydantic-settings reads a
`secrets_dir` where the file name is the setting name — so
`/run/secrets/api_key_hmac_pepper` populates `api_key_hmac_pepper` with no
mapping table in code.

pydantic-settings' default precedence is: init kwargs, environment, `.env`,
secret files. The mount is *last*.

That ordering is defensible for a library and wrong for this deployment. A
production node accumulates a `.env` — from the first manual bring-up, from a
debugging session, from a copy of `.env.example` somebody edited to get a
container to start. Under the default order, that leftover file silently
overrides every secret the deployment mounted. The platform comes up, works, and
is running on values from a file nobody remembers writing, with nothing in any
log saying so. The failure mode is not an outage; it is a signing key that is
not the one being rotated.

## Decision

**Move exactly one pair.** Precedence, highest first: init kwargs, environment,
**secret files**, `.env`.

The reasoning is a claim about intent: *a `.env` on a production node is nearly
always residue; a mount is always deliberate.* Somebody had to write the secret
into the orchestrator for the mount to exist.

The environment stays on top so a test or a one-off override can still win, and
`frozen=True` means nothing changes after construction.

## Consequences

The order now differs from pydantic-settings' documented default, which is a
thing a reader will assume rather than check. It is stated in the docstring of
`settings_customise_sources` with the failure it prevents, and
`tests/unit/test_secret_files.py::test_the_mount_beats_a_leftover_dotenv`
asserts it — the assertion existing is what stops a future upgrade from
restoring the default order silently.

Local development is unaffected: there is no `/run/secrets` on a developer
machine, `secrets_dir` names a directory that does not exist, and
pydantic-settings warns about that. The warning is suppressed for exactly that
case rather than globally, so a *production* node with a missing mount still
produces one.

A secret that exists in both places now behaves differently depending on which
one an operator edits. Editing `.env` on a node with mounts appears to do
nothing, which is confusing in the moment and is the correct behaviour.

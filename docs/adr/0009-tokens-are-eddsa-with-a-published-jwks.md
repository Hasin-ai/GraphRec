# ADR 0009 — Access tokens are EdDSA-signed, with a published JWKS

**Status:** Accepted. D5 confirmed 2026-08-22.
**Phase:** 2
**Date:** 2026-08-22

## Context

D5 in BUILD_PROMPT's appendix proposes EdDSA (Ed25519) with a published JWKS,
and asks for confirmation before Phase 3. Phase 2 could not issue a credential
without choosing something, so it was built to the stated recommendation and
flagged in the Phase 2 report. That recommendation has since been confirmed, so
no rework followed.

## Decision

**EdDSA (Ed25519), not HS256.** The deciding constraint is the per-tenant
inference process: it must verify a token locally without a control-plane round
trip. With a shared secret, every one of those processes could also *mint*
tokens. With an asymmetric key, they hold only the public half.

**The algorithm is pinned at the verifier.** `jwt.decode(..., algorithms=["EdDSA"])`,
a module constant, never read from the token header. This is what defeats
algorithm confusion, where an attacker re-signs a token with HS256 using the
published public key as the HMAC secret. Unpinning it to include `HS256` and
`none` was verified to make `test_an_hs256_forgery_is_refused` fail; restoring it
made it pass. The forgery in that test is hand-crafted with `base64`/`hmac`,
because PyJWT refuses to sign HS256 with a PEM and would otherwise be testing its
own guard rather than ours.

**The realm is an explicit claim, not an inference.** A token carries `realm`,
and `verify_tenant_access` and `verify_platform_access` each check it. A tenant
token has `tid` and `role`; a platform token has `perms[]` and no `tid` at all.
Deducing the realm from the presence of `tid` would make a claim's *absence*
load-bearing, and absence is exactly what an attacker controls.

**Refresh tokens are signed, not opaque.** The `refresh_sessions` row is under
RLS, so reading it requires a bound context, which requires a verified claim.
An opaque token would have to be looked up before anything was verified.

**One key id, published at `/.well-known/jwks.json`.** Public half only. The
private key is generated per environment by `scripts/gen_jwt_keys.py`, written
`0600` via `os.open`, and never committed.

## Consequences

- Verification needs no shared secret and no network call, which is what makes a
  per-tenant inference process viable without giving it minting authority.
- Key rotation is a JWKS with two entries and a `kid` on each token. The
  machinery is present; the rotation procedure is not yet written.
- The signing key is never baked into an image and never committed. The
  container mounts `./secrets` read-only at `/app/secrets`; `secrets/` is
  ignored by both git and Docker. A key that ships in a layer is a published
  key, and every token ever issued under it is forgeable.
- Nothing outside `graphrec/auth/tokens.py`, `scripts/gen_jwt_keys.py`,
  `routers/well_known.py` and the token settings block reads the algorithm, so
  the choice stays reversible even though it is now settled.

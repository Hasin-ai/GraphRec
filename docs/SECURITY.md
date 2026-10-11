# Security

How GraphRec protects tenants from each other and from the outside, what it
deliberately does not do, and how to report a problem.

## Tenant isolation

Isolation is enforced in three layers, so a bug in one does not expose data:

1. **The credential decides the tenant.** Bearer tokens and API keys carry or
   resolve to exactly one tenant; no request parameter can select another
   (NR-NF-02, BRULE-01). Requests that try (`?tenant_id=`) are refused.
2. **PostgreSQL row-level security, forced, on every tenant-owned table.** The API,
   worker and scheduler connect as `graphrec_app`, a role *without* `BYPASSRLS`;
   each transaction sets `app.current_tenant_id` and the policies admit only that
   tenant's rows, for reads and writes. Cross-tenant operator views use
   `SECURITY DEFINER` functions that return only what the platform screen needs
   (counts, tenant names and statuses), never tenant content.
3. **Non-disclosing errors.** Another tenant's resource is "not found", exactly as a
   resource that does not exist.

`tests/integration/test_isolation_sweep.py` exercises every route the application
exposes with no credential, with tenant credentials against platform routes, and
with tenant B's bearer token and API key against tenant A's resource ids; it fails
if any response succeeds or contains A's data. Further tests cover RLS directly with
the runtime role.

## Credentials

| Credential | Storage | Notes |
|---|---|---|
| Console passwords | argon2id | generic failure messages; per-account and per-source sign-in limits |
| Access tokens | not stored (signed JWT, 15 minutes) | carry role scopes; a role, status or password change ends sessions (`auth_epoch`) |
| Refresh tokens | SHA-256 hash only | single use, rotated on every refresh; reusing a rotated token revokes all of the user's sessions and is recorded as a security event; the absolute sign-in lifetime never extends |
| API keys | HMAC-SHA-256 with a server pepper, versioned | the secret is shown once; keys carry delegated scopes, can be rotated with a grace period and revoked; API keys can never manage keys or users |
| Setup, invitation and recovery tokens | hash only | single use, expiring; shown once on screen (no email, D-05) |
| Operator sign-ins | argon2id; tokens for a separate `graphrec-platform` audience | roles re-read on every request |

## Roles

- **Tenant administrator**: everything in the tenant, including members, API keys,
  model activation, plans view and the tenant audit trail.
- **Tenant developer**: integration credentials, catalog, events and training data;
  cannot activate models or manage members.
- **API keys**: only the scopes delegated at creation (storefront serving, events,
  catalog reads…).
- **Platform operators** (D-04): `platform` (tenant status, recovery),
  `plan_management` (plans, quotas), `monitoring` (status, failures, usage), `audit`
  (audit history), `operator_admin` (operators). Every platform route declares its
  roles; a route without a declaration is refused. Operators' actions are attributed
  to them in the audit log; tenants see "GraphRec operator" and the reason, not the
  person (D-17).
- **Suspended or deleting tenants** (D-13): members sign in to a restricted session
  that can only read the workspace status.

The bootstrap `PLATFORM_ADMIN_TOKEN` grants full access only in development. In
production it can only create the first operator and should then be removed.

## Abuse limits

Sign-in, registration, setup, recovery, API-key administration, usage reads and
recommendation traffic are rate limited per subject and source through Redis, shared
by all API processes. The client address comes from `X-Forwarded-For` only when the
direct peer is a trusted proxy (`FORWARDED_ALLOW_IPS`): in production that is the
console's nginx at a fixed internal address, behind Caddy, which replaces any
`X-Forwarded-For` a client sends. Development Compose trusts `*` because the API
port is bound to localhost. Request bodies are bounded
before parsing (`MAX_REQUEST_BODY_BYTES`, bulk and upload limits); statements are
bounded by `DB_STATEMENT_TIMEOUT_MS`. Plan quotas are enforced under a per-tenant
lock and are never overshot.

## Transport and browser

Production terminates TLS in Caddy (automatic certificates, HSTS). nginx adds
`Content-Security-Policy` (same-origin scripts and connections, no framing),
`X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` and
`Permissions-Policy` to every response. Console sessions live in `sessionStorage`
(one tab), never in cookies, so there is no cross-site request forgery surface.

## Audit

Every state change in a tenant — and every denial of an authenticated request — is
written to an append-only audit log with the actor, outcome, correlation id and,
where the action takes one, the reason. The runtime role cannot update or delete
audit rows. Security events (failed sign-ins, token reuse, contract violations)
are kept with hashed sources.

## Production gates

With `GRAPHREC_ENV=production` the services refuse to start with default,
placeholder or short secrets, development database passwords or without Redis;
placeholder training and tenant-registered model versions are refused; `/metrics`
needs a token.

## Not provided

Stated plainly so nobody assumes otherwise: no email delivery (links are shown on
screen, D-05); no multi-factor authentication or SSO; no field-level encryption
inside PostgreSQL (use encrypted disks and encrypted backups); serving "replicas"
are logical capacity slots within the API processes, not isolated per-tenant
inference servers (D-07).

## Reporting a vulnerability

Report suspected vulnerabilities privately to the maintainers (the repository
owner) rather than in a public issue, with the steps to reproduce and any
correlation id. Please do not test against deployments you do not operate.

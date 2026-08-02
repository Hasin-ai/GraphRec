# GraphRec

GraphRec is a multi-tenant recommendation platform developed as small, working
vertical slices. Completed paths include public tenant registration,
tenant-user sign-in, the protected subscription/quota overview, and current
usage reconciliation, plus scoped API-key lifecycle management.

## Current vertical slice

- Registration: `http://localhost:5180/auth/register` -> `POST /v1/tenants`
- Sign-in: `http://localhost:5180/auth/login` -> `POST /v1/auth/login`
- Subscription: `http://localhost:5180/app/subscription` -> `GET /v1/subscription`
- Usage: `http://localhost:5180/app/usage` -> `GET /v1/usage`
- API keys: `http://localhost:5180/app/integration/api-keys` -> redacted
  list/detail plus create/rotate/revoke endpoints
- Durable effects include tenant setup, hashed tenant-scoped refresh sessions,
  an immutable tenant usage ledger, and versioned HMAC-only API-key verifiers.
- Isolation uses forced PostgreSQL row-level security; protected reads derive
  tenancy from a verified bearer or API key and accept no tenant selector.

## Local sign-in demonstration

Public registration still creates an invited administrator because account
setup is not contracted. Create a separate local-only demo credential, then
sign in through the documented endpoint:

```bash
docker compose --env-file .env.example --profile demo run --rm demo-account
```

- Email: the `DEMO_LOGIN_EMAIL` value in `.env` (example default:
  `demo-admin@example.org`)
- Password: the `DEMO_LOGIN_PASSWORD` value in `.env`

The bootstrap is not a public setup endpoint and must not be enabled on a VPS.

The registration contract intentionally asks only for a business name and
administrator email. Password/account setup remains blocked by
`GAP-API-018`; the registration path does not invent a password field or
activate its invited administrator.

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:5180/auth/login` for the sign-in demonstration or
`http://localhost:5180/auth/register` for registration. After signing in, use
**View subscription** for plan limits or **View usage** for the reconciled
current-month usage and remaining allowance. Use **Manage API keys** to create,
inspect, rotate, and revoke a scoped server credential. One-time secrets must
be saved before closing their confirmation view. The API health check is
available at `http://localhost:8010/healthz` for local operations only. Both
host ports are configurable in `.env`.

## Verify

```bash
docker compose exec -T api pytest -q
docker compose --profile test run --rm frontend-test
```

See `docs/implementation/` for the path roadmap, current acceptance criteria,
traceability, decisions, and known specification gaps.

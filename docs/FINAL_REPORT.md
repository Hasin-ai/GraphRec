# GraphRec — final report (Phases 1–6)

Date: 2026-10-08 · Version 1.1.0 · Branch `phase2/anomaly-fixes` (59 commits on top of `base`).
Every statement below is backed by code, a test, or a measurement in this repository.

## Result

GraphRec is one product: one API, one console (`web/`), one Python SDK, one version
number, one reference storefront (Reel), deployable on a single host with Compose and
Caddy. **All 101 SRS requirements are Done** (7 of them in the form fixed by a recorded
owner decision) and **each is cited by at least one test** (`docs/TRACEABILITY.md`,
enforced by `tests/test_srs_traceability.py`). No requirement was deferred without
sign-off.

## What changed, per phase

**Phase 1 — analysis.** `docs/GAP_ANALYSIS.md`: architecture, 101-row traceability, 34
anomalies (A-01…A-34), decisions needing sign-off.

**Phase 2 — anomalies.** Shared, proxy-aware rate limits that never fail open (A-01);
refresh-token rotation with reuse detection (A-05); one error envelope with correlation
ids, 405 mapped correctly (A-03, A-23); `GRAPHREC_ENV` profiles refusing weak secrets
(A-10); development-only placeholders (A-02); `/readyz` with live dependency checks
(A-27); RLS on `registration_requests` (A-17); bounded chunked bodies (A-18); recent
popularity fallback and honest provenance (A-19, A-20); worker transient retry, graceful
shutdown and a real kill test (A-21); UTC sessions (A-15); multi-stage image, locked
dependencies (A-12); security headers (A-14); typed contracts (A-13); audit reasons and
filtered platform audit (A-09); CI gates and committed OpenAPI.

**Phase 3 — one SaaS product.** `frontend_02` → `web` (D-08). Generated TypeScript types
from OpenAPI plus a compile-time contract against the console's types; CI fails on drift.
Operator accounts with roles and attributed audits (D-04); plan-limit semantics (D-11);
status-only sessions for suspended tenants (D-13); member management — role, lock,
unlock, disable, resend (UC-27, D-20); tenant audit trail `GET /v1/audit` (UC-31, D-17);
cross-tenant usage `GET /v1/platform/usage` (UC-29). Console pages, SDK methods and
tests for each.

**Phase 4 — complete the SRS.** XR-F-10 common-set comparison of candidate, active
version and popularity baseline, shown on the model page (D-19); UC-24 usage by billing
period (D-18); XR-NF-03 tests for cooldown and quota on scheduled retraining; NR-NF-08
fallback chaos matrix; NR-NF-04 load test (`scripts/load_test.py`, D-15) and
`docs/PERFORMANCE.md`; ID-cited tests for all 101 requirements.

**Phase 5 — production readiness.** Prometheus `/metrics` (shared across processes,
route-template labels, token-protected; D-22) and JSON logs with correlation ids
(ER-NF-09); isolation sweep over every route × credential; production Compose overlay
with Caddy TLS, only ports 80/443 published (D-23); backup and staged restore scripts;
retention job (D-21); `docs/DEPLOYMENT.md`, `OPERATIONS.md`, `SECURITY.md`, `API.md`;
marketing claims checked against the code (D-24). Reel storefront bugs fixed (below) and
the Facet storefront archived (D-09).

**Phase 6 — verification.** Fresh clone, fresh database, every suite, the load test, an
independent review and fixes for what it found.

## Reel storefront: bugs fixed

1. Browse filters overflowed the page on phones (2,156 px wide at 390 px).
2. Opening an unknown film requested "more like" for it and produced a 422.
3. Per-visitor state (previous lists, impression ids) grew without bound in the server.
4. The Insight → Status tab always showed the offline MovieLens checkpoint card, even for
   a version GraphRec trained on the store's own data, and showed the configured version
   rather than the one that served the last list (wrong after a rollback or fallback).
5. `bootstrap_reel.py` wrote unquoted `.env` values with spaces (broke shell and Compose
   use) and printed whole API objects. New `--train` option for hosts without the
   checkpoint.

Verified live: bootstrap → Reel → `scripts/e2e_check.py` (fallback, session, personalized,
duplicate replay) and a browser walk at 1366 px and 390 px with no errors or overflow.

## Test and load results (fresh clone of the final commit, fresh database)

| Suite | Result |
|---|---|
| Migrations | upgrade from empty → `0038`, downgrade to `0031`, upgrade again: clean |
| Backend unit + integration (`pytest tests`) | 309 passed, 14 skipped (the skipped tests need the Beauty and MovieLens checkpoints, which are not in the repository) |
| Python SDK (unit + contract) | all passed |
| Web: type check incl. API contract, `vitest`, build, `npm audit` | 84 tests passed; 0 vulnerabilities; generated types match `openapi.json` |
| Browser end to end (Playwright, 7 specs) | 17 passed (one spec updated to D-11 semantics, then passed) |
| Reel storefront | 13 passed |
| SRS traceability | 101/101 cited |
| Load, 8 concurrent shoppers, 60 s, trained model | 79.5 req/s, p95 152.6 ms, p99 180.4 ms, 0 failures |

Full load sweep (1/8/32/64 shoppers) and its reading: `docs/PERFORMANCE.md`. Supported
load on the 2-vCPU reference host: about 80 mixed requests/s at 8 concurrent shoppers.

## Independent review

A separate agent reviewed Phases 3–5 without having seen the work. Fixed: a race that
could leave a tenant with no administrator (now serialised per tenant); unbounded metric
labels from arbitrary HTTP methods; the version comparison could fail a training job
(now reported as unavailable instead) and could flatter an active version trained on the
same events (now stated on the page); production trusted `X-Forwarded-For` from any
container (now only nginx's fixed address); nginx overwrote the forwarded scheme; restore
dropped the database before knowing the dump would load (now restores into a staging
database first); three overstated SRS citations (replaced by honest citations and new
tests for XR-NF-01 and UC-25). Accepted and recorded below: the audit keyset cursor can
skip rows with identical timestamps at a page boundary; the traceability guard checks that
an ID is cited, not what the test asserts (citations were reviewed by hand instead).

## Decisions and deferrals

All in `docs/DECISIONS.md`. Owner decisions: D-04 operator accounts (approved), D-05 email
(**not approved** — links are shown on screen; production readiness "email" is not
delivered), D-07 real per-tenant replicas (deferral approved — capacity is logical),
D-09 Reel as reference storefront, D-10 Compose + Caddy, D-11 plan-limit semantics, D-13
suspended tenants. Decided and recorded during the work: D-08, D-14, D-15, D-17…D-24.

## Risks and known limits

- **Single host.** One PostgreSQL, one Qdrant, one training worker. Backups are the
  recovery path; there is no failover.
- **Capacity.** About 80 req/s on 2 vCPU; single events from one tenant serialise on that
  tenant's quota lock under heavy load (batch them). Training shares the API's CPUs.
- **No email, MFA or SSO**; recovery is operator-issued.
- **Serving replicas are logical** (D-07), not isolated inference servers.
- **Checkpoint-based tests** (14) run only where the model artifacts are mounted.
- **Untested in this environment:** the Compose production overlay, Caddy and the backup
  and restore scripts were not run end to end (no Docker daemon here). Their parts were
  checked separately: `docker compose config` resolves the overlay; the PostgreSQL dump
  and restore round trip and the Qdrant snapshot upload were run against local services.
  Run `docs/DEPLOYMENT.md` on a staging host before going live.
- Audit pagination edge case and traceability-guard limit (see review).

## Deploy (exact commands)

```bash
git clone <repository> graphrec && cd graphrec && git checkout phase2/anomaly-fixes
cp .env.example .env
# set GRAPHREC_ENV=production and every CHANGE secret (python3 -c "import secrets; print(secrets.token_urlsafe(48))")
echo "GRAPHREC_DOMAIN=graphrec.example.com" >> .env
echo "ACME_EMAIL=ops@example.com" >> .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
curl -fsS https://graphrec.example.com/readyz
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm \
  -e OPERATOR_PASSWORD='<12+ characters>' api \
  python -m scripts.create_operator --email ops@example.com --name "Ops Lead"
# remove PLATFORM_ADMIN_TOKEN from .env, then:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# cron: scripts/backup.sh /var/backups/graphrec  and  ... run --rm retention   (docs/DEPLOYMENT.md step 4)
```

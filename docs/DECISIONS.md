# Decisions

Each entry records a choice made while taking GraphRec from vertical slices to one product, why it was made, and whether it still needs the owner's sign-off. Anomaly numbers (A-xx) and decision numbers (D-xx) refer to `docs/GAP_ANALYSIS.md`.

Status values: **Decided** (made under the ground rules, reversible), **Needs sign-off** (product-defining or irreversible; not implemented until approved), **Deferred** (out of scope for now, with the reason).

---

## D-01 Preserve uncommitted work before Phase 2 — Decided (2026-10-07)

The working tree held 49 uncommitted files (marketing site, playground, `GET /v1/events`, `apps/reel-storefront/`, auth and event changes). They were committed unchanged as `chore: snapshot in-progress work before Phase 2` on branch `phase2/anomaly-fixes`, and every Phase 2 fix is a separate commit on top. Nothing was discarded; `main` is untouched.

## D-03 Refresh tokens: rotation with reuse detection — Decided (2026-10-07)

Login already issued refresh tokens that nothing accepted (A-05). Removing them would have kept the 15-minute forced sign-out, so rotation was completed instead:

- `POST /v1/auth/refresh` accepts a refresh token once and returns a new pair (migration `0032`).
- A rotated session keeps the original absolute expiry (`REFRESH_TOKEN_TTL_SECONDS`), so refreshing never extends a sign-in.
- Presenting an already-rotated token is treated as theft: every session of that user is revoked (refresh sessions and, through `auth_epoch`, outstanding access tokens) and a `refresh_token_reuse` security event is recorded.
- The console refreshes 30 seconds before expiry and once on `token_expired`, in a single flight, because a second use of the same token would sign the user out.

This completes the existing auth model rather than changing it.

## D-06 Development-only fakes — Decided (2026-10-07)

Placeholder training (random embeddings served with a zero query vector) and `POST /v1/model-versions` (tenant-asserted metrics) stay available for local development and tests, but `GRAPHREC_ENV=production` refuses them, refuses to activate or serve non-DGSR versions, and the console hides the placeholder option. Fake `rustfs://` URIs became honest `placeholder://` / `unregistered://` markers.

## D-08 Rename `frontend_02/` — Not yet done

The rename to `web/` touches Compose, both Dockerfiles, Playwright, READMEs and SDK docs. It is mechanical and will be done as one commit in Phase 3 so that it does not mix with behaviour changes. Until then every reference stays `frontend_02/`.

## D-14 XR-F-04 brand and seasonality — Decided (2026-10-07)

The SRS says "diversity, category, brand, freshness, **or** seasonality rules". Diversity, category caps and freshness are implemented, bounded and versioned (XR-NF-02). Brand and seasonality are not added.

## Rate limits shared through Redis, never failing open — Decided (2026-10-07)

Authentication, registration, API-key, subscription and usage limits moved from per-process memory to the Redis sliding window already used for recommendation admission (A-01). When Redis is unavailable they fall back to a bounded per-process window with the same limit: limits degrade to per-process, not to unlimited. Recommendation admission keeps its documented fail-open behaviour (D16), because refusing all traffic when Redis is down would contradict NR-NF-08.

The real client address comes from `X-Forwarded-For` only when the request arrives from a proxy listed in `FORWARDED_ALLOW_IPS`. Compose binds the API port to `127.0.0.1` and trusts nginx; a deployment that publishes the API port must not use `*`.

## Audit reasons through a database trigger — Decided (2026-10-07)

ER-F-11 needs the reason for credential, activation, rollback, quota, plan and operator actions. Most of those audit rows are written inside SECURITY DEFINER SQL functions. Rather than replace each function, migration `0034` adds a `BEFORE INSERT` trigger on `audit_logs` that copies the transaction-local setting `app.audit_reason` into `redacted_details.justification`. (`reason` already holds machine causes such as `model_not_ready`.) The same mechanism reserves `app.audit_actor` for operator identities (D-04). A tenant status change requires a reason (UC-27); the other actions accept an optional one and the console asks for it.

## One product version — Decided (2026-10-07)

`VERSION` at the repository root (now `1.1.0`) is the single version of the API, the console build and the Python SDK. A test fails when any of them drift. `1.1.0` follows the already released SDK `1.0.0` and its additive changes (`events.list`, `auth.refresh`, `meta`, `ready`, `plans`).

## Logical serving capacity is labelled as such — Decided (2026-10-07)

The console's Service Status page now states that serving capacity is logical: each unit adds concurrent recommendation slots enforced by every API process, and no separate serving instance is started. Real replica scaling is decision D-07 below.

## Unmeasured usage is flagged, not zero — Decided (2026-10-07)

`replica_runtime_minutes` was always reported as `0`, because nothing records it. Usage dimensions now carry `measured`; this one is `false` and the consoles show "Not measured yet". `inference_replicas` now reports the tenant's current ready serving units instead of a ledger sum that nothing wrote.

## Recommendation provenance — Decided (2026-10-07)

`model_version_id` in a recommendation response is the version that produced the ranking, and is `null` when a fallback served it. The new `active_model_version_id` reports the active version. Customers are created only from accepted interactions; a recommendation for an unknown identifier links to no customer.

## Recent popularity — Decided (2026-10-07)

The cold-start fallback counts interactions in a window (`FALLBACK_POPULARITY_WINDOW_DAYS`, default 30) that ends at the tenant's latest interaction rather than at the current time. Backfilled history therefore stays usable, and the aggregation is bounded by the existing `(tenant_id, occurred_at)` index.

---

## Needs your sign-off

| # | Decision | Recommendation | Why it is waiting |
|---|---|---|---|
| D-02 | Source for the public marketing site | Send `frontend_02/LANDING_PAGE_PROMPT.md`. It is not in the repository; the in-progress marketing pages are the only spec today | The file is missing |
| D-04 | Operator accounts with roles (`platform`, `plan_management`, `monitoring`, `audit`), argon2 passwords, audit attribution; `PLATFORM_ADMIN_TOKEN` kept only to create the first operator | Approve | Changes the auth model |
| D-05 | Email delivery: SMTP through stdlib `smtplib` plus a development outbox; self-service password recovery | Approve | Adds an outbound integration and changes the recovery flow |
| D-07 | Defer real per-tenant serving replicas; keep logical per-tenant slot capacity (now labelled in the UI) | Approve the deferral | Deferring an SRS requirement (XR-F-08) |
| D-09 | Which storefront is the reference client: `apps/demo-storefront` (Facet) or `apps/reel-storefront` | Keep one behind `--profile demo` | Deleting an app |
| D-10 | Production target: single-host Compose with Caddy (automatic TLS), or Kubernetes/Helm; and the domain | Compose with Caddy | Product-defining |
| D-11 | Plan-limit semantics: `active_model_versions` counts non-archived retained versions; Pro `concurrent_training_jobs` becomes 1 (BRULE-06, one worker); `maximum_training_duration_minutes` is enforced; `queued_messages` is removed or enforced | Approve | Changes plan limits |
| D-12 | Stray material: move `Claude outputs/`, root `qa_*` scripts and `.env.bak-qa` to an ignored `archive/`; keep `Palette and form specs/` as `docs/design-reference/`; remove build output | Approve | Deleting or moving your files |
| D-13 | Suspended tenants: allow a restricted sign-in that sees only `/account/tenant-status` | Approve | Changes what a suspended tenant can do |
| D-15 | Run the real Compose stack: allow Docker in this session, or run it on your machine | Either | Tooling access |
| D-16 | CI on GitHub Actions | Approve | Needs the repository on GitHub |

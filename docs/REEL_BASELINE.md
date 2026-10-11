# Reel Storefront: Baseline Verification and Diagnostic Report

**Date:** 2026-10-08  
**Branch:** `reel/production-readiness`  
**Standard:** GraphRec Decision D-09 (Reel is the reference client and capability proof for GraphRec)  

---

## 1. Environment & Infrastructure Baseline

| Dimension | Specification / Observed State |
|---|---|
| **Host Operating System** | Windows 11 (build environment with PowerShell) |
| **Python Version (Host)** | Python 3.14.7 |
| **Python Version (Containers)** | Python 3.12 (`python:3.12-slim`) |
| **Node.js / npm (Host)** | Node v24.19.0 / npm 10.9.2 |
| **Node.js (Containers)** | Node 22 (`node:22-alpine`) |
| **GraphRec API Container** | `graphrec-api-1` running FastAPI on port 8010 (mapped to 8000), healthy |
| **PostgreSQL Container** | `graphrec-postgres-1` (Postgres 17.5-alpine) on port 5432, healthy |
| **Redis Container** | `graphrec-redis-1` (Redis 7.4.2-alpine) on internal network `graphrec_default:6379`, healthy |
| **Qdrant Vector DB** | `graphrec-qdrant-1` (v1.12.0) on ports 6333-6334, healthy |
| **Reel Storefront Container** | `reel-reel-1` (`graphrec/reel-storefront:local`) on port 5290, healthy |
| **Console Web Container** | `graphrec-frontend-1` on port 5180, healthy |
| **DGSR Checkpoint Artifact** | Present at `model_artifacts/dgsr_movielens_32m` (`best.pt` 7.3 MB, `interactions.npz` 5.2 MB, `id_maps.json`, `config.json`) |

---

## 2. Test Suite Baseline Results

All suites were executed and verified green prior to making code modifications:

1. **Python SDK (`sdks/python/tests`)**:
   - Command: `python -m pytest sdks/python/tests`
   - Result: **368 passed in 7.50s** (100% pass rate)
2. **Web Console (`web/`)**:
   - Command: `npm test -- --run`
   - Result: **15 test files passed, 86 tests passed in 12.11s** (100% pass rate)
   - Build: `tsc -b && vite build` built cleanly in 7.49s
3. **Reel Storefront (`apps/reel-storefront/tests`)**:
   - Command: `python -m pytest apps/reel-storefront/tests`
   - Result: **13 passed in 2.21s** (100% pass rate)

---

## 3. Systematic Diagnostic Verification (Hypotheses A1 – E)

Every item in the diagnostic list from `docs/REEL_PRODUCTION_PROMPT.md` was investigated with concrete code examination, curl requests, or script executions.

| # | Hypothesis | Status | File / Location | Reproduction Evidence |
|---|---|---|---|---|
| **A1** | Local state is a second source of truth | **CONFIRMED** | `app/store.py:120-164`, `app/routes/insight.py:20` | `LiveLog` stores events in `state/live_events.jsonl` loaded into memory; `history_for` manually combines hard-coded `persona.history` with live rows instead of querying GraphRec (`client.storefront.events.list`); scans linearly per request (`for_shopper`). Multiple workers cause drift. |
| **A2** | In-memory shelf state is lost or inconsistent | **CONFIRMED** | `app/store.py:186-196`, `app/routes/recommendations.py:93,111,136` | `LastLists` and `impressions` are in-memory `BoundedDict` instances bound to a single worker process. Restart or 2 workers breaks diff calculation ("First list for this shelf") and drops impression links during `/feedback/click`. |
| **A3** | Silent telemetry failure | **CONFIRMED** | `app/routes/recommendations.py:112`, `app/routes/events.py:57`, `app/routes/recommendations.py:133` | Impression feedback swallows errors with `except APIError: pass`; conversion feedback has `except Exception: out.feedback = "conversion failed"` without error logging or metrics; `/feedback/click` has no error handling. |
| **A4** | Thin event semantics | **CONFIRMED** | `app/routes/events.py:25,37,43` | All actions hard-coded as `WATCH_EVENT = "rating"` with rating 5. No exercise of `view`, `click`, `add_to_wishlist`, `purchase`, rating range (1-5), and events carry server `now` rather than client timestamp. |
| **A5** | Mean-user vector approximation unmeasured | **CONFIRMED** | `app/routes/recommendations.py:70-76` | Anonymous and `more_like` routes invoke session path which falls back to mean-user vector without measuring or exposing representation distance or quality. |
| **A6** | Unmapped items dropped silently | **CONFIRMED** | `app/routes/recommendations.py:98-101` | When GraphRec returns a product ID missing from `films.json`, it is silently skipped with `omitted += 1; continue` without alerting catalogue drift or failing readiness. |
| **B1** | Identity is an unsigned cookie | **CONFIRMED** | `app/dependencies.py:44-48,58-62` | `reel_persona` cookie is a raw string (`anon`, `maya`, etc.) with no cryptographic signature or server-side session token validation. Can be arbitrarily tampered in browser. |
| **B2** | Only 3 personas | **CONFIRMED** | `app/store.py:107-118`, `data/personas.json` | Hardcoded personas (`maya`, `theo`, `sam`, `anon`). Cannot select an arbitrary user ID or test a brand new cold-start visitor without altering code/JSON. |
| **B3** | No CSRF protection, rate limiting, or body limits | **CONFIRMED** | `app/main.py`, `app/routes/events.py`, `app/routes/recommendations.py` | No rate limiting middleware (Redis-backed), no body size limits, no Origin/CSRF verification on POST endpoints (`/watch`, `/recommendations`, `/feedback/click`). |
| **B4** | Missing security headers & insecure cookies | **CONFIRMED** | `app/main.py:40-52` (live curl) | Curl inspection of live responses (`curl.exe -i http://localhost:5290/api/reel/session`) confirms absent CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy. `reel_cookie_secure` defaults to `False`. |
| **B5** | Weak SPA path check | **CONFIRMED** | `app/main.py:70` | Fallback check uses `if path and ".." not in path and candidate.is_file():` instead of strict resolved path containment (`is_relative_to(dist.resolve())`). |
| **B6** | Stray files and uncommitted secrets in tree | **CONFIRMED** | `apps/reel-storefront/.env`, `apps/reel-storefront/_xfer/` | `apps/reel-storefront/.env` committed with live API key; `_xfer/` contained migration tarballs (`reel.tgz`, `sdk.tgz`). |
| **C1** | Missing `/healthz` and `/readyz` | **CONFIRMED** | `app/main.py`, `Dockerfile:24-25` | Neither `/healthz` nor `/readyz` exists. Container healthcheck pings `/api/reel/genres` which does not test GraphRec, Redis, or active model readiness. |
| **C2** | Lack of structured logs & correlation ID propagation | **CONFIRMED** | `app/main.py:23`, `app/graphrec.py:33-41` | Basic string logging without JSON formatting. No `X-Correlation-ID` header generated or propagated across Reel and GraphRec requests. |
| **C3** | Unpinned Docker dependencies & non-idempotent bootstrap | **CONFIRMED** | `Dockerfile:16`, `scripts/bootstrap_reel.py:91-100` | Dockerfile contains unpinned packages (`fastapi>=0.116`, `uvicorn[standard]>=0.35`, etc.). `bootstrap_reel.py` generates new tenants on every run without idempotency. |
| **C4** | GraphRec outage behavior untested | **CONFIRMED** | `app/routes/recommendations.py:86-89` | Only partial handling in `/recommendations`; session, insight, and event endpoints fail or produce unhandled errors during 503 or network partitions. |
| **D1** | Lack of automated DGSR capability proof | **CONFIRMED** | `scripts/`, `app/` | No automated test harness to prove DGSR capabilities (P1–P19) on demand. Previous script (`e2e_check.py`) mutated demo personas. |
| **D2** | Tests rely exclusively on `FakeGraphRec` | **CONFIRMED** | `tests/test_api.py:25` | Reel unit tests mock GraphRec client with `FakeGraphRec`, never validating actual model inference against the live engine. |
| **D3** | No browser-level Playwright tests | **CONFIRMED** | `apps/reel-storefront/` | No Playwright configuration or specs exist for Reel frontend flows. |
| **D4** | No live quality metrics computed | **CONFIRMED** | `app/routes/insight.py:51-64` | Status tab displays static model card from JSON; no live calculation of Hit@10 or Recall@10 against baseline. |
| **E1** | TypeScript types manually written | **CONFIRMED** | `frontend/src/types.ts` | Hand-written type definitions not generated from FastAPI OpenAPI schema. |
| **E2** | Missing UI loading/empty/error states | **CONFIRMED** | `frontend/src/components/Shelf.tsx`, `frontend/src/pages/Home.tsx` | Shelves lack distinct skeleton loaders, retry actions, and "GraphRec unavailable" error treatments. |
| **E3** | Accessibility deficiencies | **CONFIRMED** | `frontend/src/components/Insight.tsx` | Drawer lacks ARIA dialog attributes, focus trapping, and keyboard tab management. |

---

## 4. Phase 0 Cleanup Actions Completed

1. **Archived Migration Tarballs**:
   - `apps/reel-storefront/_xfer/` (`reel.tgz`, `sdk.tgz`) relocated to `archive/reel-xfer/`.
   - Updated `archive/README.md` to document the archived migration artifacts.
2. **Fixed Pytest Script Resolution**:
   - Updated `tests/test_api.py` `test_bootstrap_quotes_env_values_with_spaces` to resolve `scripts/bootstrap_reel.py` relative to the test file rather than assuming working directory.
   - All 13 tests now pass reliably from both repo root and `apps/reel-storefront`.
3. **Frontend Build Toolchain Aligned**:
   - Updated `apps/reel-storefront/frontend/package.json` to Vite 7.3.6 and `@vitejs/plugin-react` 4.6.0 (matching `web/`), resolving Node 24 Windows build deadlock.
   - Production bundle compiles in ~1.04s.

---

## 5. Execution Roadmap

- **Phase 1: Backend Correctness & Consistency**
  - GraphRec as single source of truth for events and history (`client.storefront.events.list`).
  - Durable Redis storage for shelf diffs and impression linking.
  - Telemetry retry with structured error logging.
  - Multi-event model (`view`, `click`, `add_to_wishlist`, `rating`, `purchase`).
  - Signed session cookies and arbitrary user ID / cold-start persona.
  - Security headers, strict Origin verification, rate limiting, and safe path containment.
- **Phase 2: Operability**
  - `/healthz` and comprehensive `/readyz` (GraphRec, Redis, catalogue sync, model status).
  - Structured JSON logging with `X-Correlation-ID` and Prometheus metrics.
  - Pinned Docker dependencies and reproducible builds.
  - Idempotent `bootstrap_reel.py`.
- **Phase 3: Automated Capability Proof (P1–P19)**
  - Synthetic shoppers (`proof-<runid>-<n>`).
  - Battery of 19 automated tests covering personalization, recency, dynamic updates, cold start, exclusions, and business rules.
  - CI-friendly `tiny` profile and MovieLens `full` profile.
  - Integration into UI Insight drawer ("Proof" tab).
- **Phase 4: Frontend Polish & Verification**
  - Generated TypeScript types from OpenAPI + CI drift check.
  - UI error/loading states and accessibility enhancements.
  - Playwright end-to-end tests.
- **Phase 5: Final Handover & Report**
  - Full validation run and `docs/REEL_FINAL_REPORT.md`.

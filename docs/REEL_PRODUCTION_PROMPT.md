# Prompt: make Reel-Store production-ready and make it prove that GraphRec + DGSR really work

> Paste everything below the line into Claude Code, started at the GraphRec repository root.

---

## Role

You are a senior full-stack and ML-platform engineer. Your job is to take `apps/reel-storefront` (Reel, a MovieLens film store: FastAPI + React, calling GraphRec through `sdks/python`) from "good demo" to **production-grade reference storefront**, and to turn it into an **instrument that proves GraphRec and its DGSR model work**, capability by capability, on demand.

Reel is the reference client for GraphRec (decision D-09). If Reel is wrong, flaky or unverifiable, nobody can trust GraphRec. Treat it as a product, not a demo.

## Ground rules (these override everything else)

1. **Evidence over claims.** Nothing is "done" until a command, test or browser run shows it. Every statement in your final report must point to a file, test name, command output or measurement. No "should work".
2. **No faking.** Never hard-code expected output, stub GraphRec in a check that claims to verify GraphRec, or paint a green badge without a real call behind it. If DGSR cannot do something (see "Declared limits"), the UI says so plainly instead of pretending.
3. **Verify my diagnosis first.** The problem list below comes from reading the code. Before fixing each item, reproduce it (test, curl or log). If it turns out to be wrong, say so and drop it.
4. **Test first, then fix.** For each defect add a test that fails on the current code, show it failing, fix, show it passing.
5. **Small commits on a branch** (`reel/production-readiness`), one concern per commit, CHANGELOG entry per user-visible change. Do not leave uncommitted work. Do not delete files; move stray files to `archive/` and list them.
6. **Do not change GraphRec's public API or plan-limit semantics** without writing the change and the reason in `docs/DECISIONS.md` and stopping to ask me. Bugs you find in GraphRec itself: fix if small and tested, otherwise log in `docs/REEL_FINDINGS.md`.
7. If Docker is unavailable in your environment, say so, use native PostgreSQL/Redis/Qdrant, and list exactly which steps were not run end to end.
8. Use the task list. Finish with an independent check: a fresh clone, fresh database, every suite green, and a short review of your own diff against this prompt.

## What I read in the code (hypotheses to verify)

### A. State and correctness
- **A1. Local state is a second source of truth.** `LiveLog` keeps every event in a JSONL file loaded into memory (`app/store.py`). Reel rebuilds the shopper's history from seeded personas plus its own log ("mirrors `_stored_history`"), instead of asking GraphRec. The Sequence tab, "Recently watched" and the ✓ marks can drift from what GraphRec really used. It also grows without bound, scans linearly per call, and breaks with more than one uvicorn worker.
- **A2. In-memory shelf state is lost or inconsistent.** `LastLists` and `impressions` are bounded dicts per process. After a restart or with two workers, diffs say "First list for this shelf" and clicks lose their impression link.
- **A3. Silent failure.** Impression feedback is `except APIError: pass`; conversion feedback is `except Exception` with no log; `/feedback/click` has no handling at all. Failed telemetry leaves no trace, so CTR numbers in the GraphRec console may be wrong without anyone knowing.
- **A4. Event semantics are thin.** Every action is a `rating` of 5 (`WATCH_EVENT`). GraphRec accepts `view, click, add_to_cart, purchase, rating, add_to_wishlist`, but Reel exercises one. Events carry server `now`, not the real action time.
- **A5. Recommendations for anonymous shoppers and "more like this"** use the mean-user-vector approximation. The UI labels it, but nothing measures how good it is.
- **A6. `omitted` items.** Ranked ids missing from `films.json` are dropped silently. That is a catalogue-sync bug signal, not just a counter.

### B. Identity and security
- **B1. Identity is an unsigned cookie.** `reel_persona` chooses which real MovieLens user you are. Anyone can edit it. Fine for a demo, wrong for "production".
- **B2. Only 3 personas.** You cannot test an arbitrary user, a brand-new user, or many users at once. The README admits a renamed persona falls back to session mode.
- **B3. No CSRF protection, no rate limiting, no body limits** on `/watch`, `/recommendations`, `/feedback/click`. Every call spends GraphRec tenant quota; a loop can exhaust the monthly allowance.
- **B4. No security headers** (CSP, frame-ancestors, referrer policy, HSTS behind TLS). `reel_cookie_secure` defaults to `False`.
- **B5. SPA fallback path check** is `".." not in path`. Replace with a resolved-path containment check.
- **B6. Secrets and junk in the tree:** `.env` with a live key, `_xfer/*.tgz`, `.pytest_cache`, `__pycache__`.

### C. Operations
- **C1. No `/healthz` or `/readyz` for Reel.** The Docker healthcheck hits `/api/reel/genres`, which proves nothing about GraphRec.
- **C2. No structured logs, no correlation id** forwarded to GraphRec (`X-Correlation-ID`), no metrics.
- **C3. Dependencies unpinned** in the Dockerfile (`fastapi>=0.116`, etc.); no lock file; single uvicorn process; API key rotation needs a restart; `bootstrap_reel.py` creates a **new tenant on every run**, leaving orphan tenants.
- **C4. GraphRec outage behaviour is untested** at the Reel level (timeouts, 429 with `Retry-After`, 503, key revoked, tenant suspended). Only a fake client is used.

### D. Verification gap (the most important)
- **D1. "Is GraphRec working?" can only be answered by a human running a script.** `scripts/e2e_check.py` mutates permanent state (it adds events to Sam's history) and needs the 7,951-film checkpoint, which is not in the repository. In CI the 14 checkpoint-dependent tests are skipped. The README's "measured" demo table says "confirm in a dry run" and nothing confirms it.
- **D2. Reel's 13 tests use a fake GraphRec client.** They test Reel's plumbing, not GraphRec or DGSR.
- **D3. No browser test for Reel.** Responsive layout and the Insight drawer were checked by hand once.
- **D4. No quality number** is computed live. Offline Hit@10 0.8313 on 1+100 sampling versus 0.576 for popularity alone is a weak claim; the full-catalogue Recall@10 12.45% versus 3.35% is better but is a static card, not something Reel can reproduce.

### E. UI and backend consistency (audit and fix; I have not read all of the frontend)
- Hand-written types in `frontend/src/types.ts` can drift from `app/schemas.py`. `web/` already solved this with OpenAPI → generated TypeScript types plus a CI drift check; do the same for Reel.
- Make sure every screen has loading, empty, error and "GraphRec unavailable" states, one error envelope end to end, no raw error strings, and the same wording for the same concept (strategy names, fallback tiers).
- Accessibility (keyboard, focus, roles, contrast), 390 px and 1366 px layouts without horizontal scroll, no console errors.

## Goals

1. **Production-ready Reel**: no process-local truth, safe by default, observable, reproducible builds, tested against the real GraphRec.
2. **A "Proof" capability**: from the Reel UI, one click (or `python scripts/prove_graphrec.py`) runs a battery of checks against the live stack and returns pass / fail / not-applicable with evidence for each DGSR capability below. It must be safe to run repeatedly (no pollution of demo personas).
3. **Consistency**: one source of truth for history and state (GraphRec, with a small cache), one error model, one set of generated types, one vocabulary.

## Work plan

### Phase 0 — Baseline (no code changes)
Run every existing suite (GraphRec backend, SDK, `web/`, Reel tests, Playwright). Record results and the environment (checkpoint present? Docker? versions) in `docs/REEL_BASELINE.md`. Reproduce each hypothesis A1–E with evidence. Output the confirmed / rejected table before changing anything.

### Phase 1 — Correct and consistent backend
- **Single source of truth.** Read a shopper's history, window and "recently watched" from GraphRec (add or use an events/history endpoint; if none exists, add `GET /v1/customers/{id}/history` to GraphRec with scope, RLS, tests, OpenAPI and SDK method). Keep the local log only as a bounded, optional cache for the Insight "receipts" view. Remove the "mirrors the API" logic.
- **Durable shared state.** Move shelf diffs and impression links to Redis (already in the stack) or a small SQLite/Postgres table, with TTLs. Behaviour must be identical with 1 or N workers; test with 2 workers.
- **Telemetry that cannot fail silently.** Impression, click and conversion feedback: retry once, log with correlation id, count failures in a metric, and expose "feedback health" in the Status tab. User actions still never fail because of telemetry.
- **Real event model.** Send `view` on film page open, `click` on shelf click, `add_to_wishlist` on a new "Save for later" action, `rating` (1–5, real value) on a rating control, and `purchase` (or "watched") as the strong signal. Send the real action time. Document which of these DGSR uses in its history (all six in `HISTORY_EVENT_TYPES`) and which it ignores in training, and show that in the UI.
- **Catalogue integrity.** At startup and in `/readyz`, compare `films.json` with GraphRec's catalogue (count, ids). Treat `omitted > 0` as an error to log and surface, not a silent drop.
- **Identity.** Replace the raw persona cookie with a signed, server-validated session (`itsdangerous`/HMAC, rotated secret). Keep three personas, add: (a) **"New visitor"** that gets a fresh, unique user id on each reset, so cold start and first-event behaviour can be shown on demand; (b) **"Pick any MovieLens user"** by id for developers (disabled when `REEL_ENV=production`).
- **Abuse protection.** Per-session and per-IP rate limits (Redis), body size limit, CSRF token or strict `Origin` check on all POSTs, request timeouts, bounded concurrency to GraphRec, `Retry-After` honoured and passed to the browser.
- **Security headers and cookies.** CSP without `unsafe-inline`, `frame-ancestors 'none'`, `Referrer-Policy`, `X-Content-Type-Options`; `Secure` cookies when `REEL_ENV=production`; refuse to start in production with insecure settings (profiles like GraphRec's `GRAPHREC_ENV`).
- **Static serving.** Fix path containment (`resolve()` + `is_relative_to`), cache headers for hashed assets, no-cache for `index.html`.
- **Errors.** One envelope `{error:{code,message,correlation_id,retryable,retry_after_seconds}}` mirroring GraphRec's; map every `APIError` subtype (401, 403, 404, 409, 422, 429, 5xx, timeout, connection) to a stable code and a calm message; unit tests for each.

### Phase 2 — Operable
- `/healthz` (process alive), `/readyz` (GraphRec reachable and `/readyz` ok, key valid, active model version present, catalogue consistent, Redis reachable). Docker healthcheck uses `/readyz`.
- JSON logs with correlation id propagated to GraphRec in `X-Correlation-ID`; Prometheus `/metrics` (route-template labels, token-protected): request latency, GraphRec call latency and outcome, fallback rate by strategy, feedback failures, rate-limit hits.
- Reproducible build: pinned `requirements.lock` (or `uv.lock`), multi-stage image, non-root, read-only root filesystem, no tests or `.env` in the image, `npm ci` only (no `|| npm install`).
- `bootstrap_reel.py`: idempotent (re-use the tenant by name unless `--new-tenant`), never prints secrets, writes `.env` with 0600 permissions, supports key rotation without restart (re-read the key on `401`, once), and a `--teardown` that suspends the demo tenant.
- `docs/REEL_DEPLOYMENT.md` and `docs/REEL_OPERATIONS.md` (env vars, secrets, rotation, backup of state, runbook for: GraphRec down, 429 storms, model rolled back, key revoked).
- Move `_xfer/`, caches and stray files to `archive/`; extend `.gitignore`.

### Phase 3 — Capability proof (the core of this task)
Build `app/proof/` plus `scripts/prove_graphrec.py` and a **"Proof" tab** in the Insight drawer (and a `/proof` page). Each check has: id, DGSR capability, setup, action, assertion, **evidence** (request ids, model version id, before/after lists, metric values), result `pass | fail | not_applicable`, duration. Results are saved as JSON and rendered as a table with expandable evidence. Exit code non-zero on any fail.

Run checks with **synthetic shoppers** (`proof-<runid>-<n>`) so personas are never polluted, and clean up by letting the run's tenant data age out or by using a dedicated `proof` tenant created by bootstrap.

| # | DGSR / GraphRec capability | How it is proven against the live API |
|---|---|---|
| P1 | **Personalization for a known training user** | For N sampled training users, GraphRec's list equals the offline reference ranking (golden file produced by `graphrec_core.dgsr.serving` on the same artifact; allow tie tolerance). Different users get different lists (pairwise overlap below a threshold). |
| P2 | **Recommendation quality over a baseline** | Held-out replay: for M users, send history minus the last item, request top-10, count how often the held-out item appears. Report Hit@10 and NDCG@10 **next to** the popularity baseline on the same users, with a confidence interval. Pass only if DGSR beats popularity by a stated margin. |
| P3 | **Sequential / recency sensitivity** | Same set of films, two different orders → lists differ in the expected direction; the most recent items influence the list more than old ones. |
| P4 | **Dynamic update without retraining** | Add 3 films of a new genre → genre share in top-10 moves toward it; add 1 of the old genre (control) → small change. Model version id is identical before and after (weights unchanged). |
| P5 | **Window behaviour (last 20)** | After >20 new events the oldest ones stop influencing the list (compare against a user whose old events were never sent). |
| P6 | **Session / anonymous recommendations** | `recent_product_ids` of one genre → list dominated by that genre; strategy `session`; no user record created (BRULE-03). |
| P7 | **Cold-start user** | Unknown user id with no events → `popular_fallback` with a stated tier; after the first event → `session`/`personalized` transition at the documented point. |
| P8 | **Unknown / new item handling** | Event on a product outside the model vocabulary is accepted but ignored by the encoder; a catalogue item the model has never seen is never returned as `personalized`; this is shown as a labelled limit, not hidden. |
| P9 | **Seen-item and explicit exclusion** | Nothing in the shopper's history or `exclude_product_ids` is returned, at positions 1–50. |
| P10 | **Eligibility filter** | Disable a recommended film in the catalogue → gone from the very next list; set it unavailable → gone; re-enable → can return. |
| P11 | **Idempotency** | Re-send an event id → `duplicate`, history unchanged, list unchanged. Re-send a recommendation request id → identical response. |
| P12 | **Determinism** | Same request twice → identical order and `request_id` semantics as documented. |
| P13 | **Business rules** | With diversity on, per-category cap respected; with freshness on, average age drops; `applied_rules` and `rules_version` present. |
| P14 | **Model lifecycle** | Activate a second version → trace shows the new version id; rollback → previous version; archive/rollback to none → `popular_fallback`. (Uses the console/SDK admin credential, not the storefront key; skipped with a clear reason if absent.) |
| P15 | **Degradation** | With Qdrant stopped → still served (in-process scoring) and the trace says so; with Redis stopped → admission degrades per documented behaviour; GraphRec unreachable → Reel shows the "unavailable" state and its own popular fallback, never a 500. |
| P16 | **Feedback loop** | Impression → click → conversion linked by `request_id`; counts visible via the GraphRec usage/metrics endpoint match what Reel sent. |
| P17 | **Tenant isolation** | A second key for another tenant cannot read this tenant's product, batch or feedback ids, and its lists contain none of this tenant's products. |
| P18 | **Training in GraphRec** (the `--train` path) | Train on a small event set through GraphRec, check version `eligible`, offline metrics recorded, common-set comparison against popularity (XR-F-10), activation, and that recommendations now come from the trained version. |
| P19 | **Throughput and latency** | N concurrent shoppers for 30–60 s: p50/p95/p99, error rate, fallback rate; compare with `docs/PERFORMANCE.md` and fail on regression beyond a tolerance. |

**CI-friendly proof without the big checkpoint.** Create a tiny synthetic DGSR artifact (about 300 users, 400 films, fast to train, committed or generated by a script with a fixed seed) and a `tiny` profile so P1–P13 and P18 run in CI in minutes. The full MovieLens run (P2 quality numbers) is a separate `full` profile that runs where the checkpoint is mounted. Remove the 14 skip-by-environment cases by giving them the tiny artifact.

**Declared limits** (show as `not_applicable` with the reason, do not fake): event type and rating value are not used as weights by the checkpoint; no content or metadata features (genre/tags do not enter the model); no item cold-start; training is offline (events change the input history, not the weights); MovieLens popularity bias in the score.

### Phase 4 — UI polish and consistency
- Generate `frontend/src/api/schema.d.ts` from Reel's OpenAPI (enable the schema in non-production, export to a committed file), delete hand-written duplicates in `types.ts`, add a CI drift check.
- Insight drawer: new **Proof** tab; **Status** tab shows readiness checks, active version, feedback health, last proof run time and result.
- Unified states for every page: skeleton, empty, error with retry, "GraphRec unavailable" with the reason and correlation id.
- Consistent wording: one glossary for `personalized / session / popular_fallback`, fallback tiers, and "model version" across Reel, the GraphRec console and the SDK docs.
- Accessibility pass (axe in Playwright), keyboard operation of the drawer and tabs, reduced motion, 390 px and 1366 px screenshots with no overflow.
- Playwright specs for Reel: anonymous → session list, switch persona with carry, watch → list changes, replay → duplicate, unknown film, GraphRec down (stop the container or route-block), proof run.

### Phase 5 — Verification and handover
- Fresh clone, fresh database, bootstrap, every suite, the proof run in both profiles, the load test.
- Independent review pass of Phases 1–4 against this prompt (a separate agent that did not see the work), fix its findings.
- Write `docs/REEL_FINAL_REPORT.md`: what changed, a table of A1–E with before / after evidence, the proof results, known limits, and anything not run (and why).

## Definition of done

- Every item A1–E is fixed with a failing-then-passing test, or rejected with evidence.
- `scripts/prove_graphrec.py --profile tiny` passes in CI without any private artifact; `--profile full` passes where the MovieLens checkpoint is mounted, and prints Hit@10 / NDCG@10 for DGSR and for popularity on the same users.
- Reel behaves identically with 1 and 2 workers and across restarts (test included).
- A GraphRec outage, 429 storm, revoked key and rolled-back model each produce a calm UI state, a log line with a correlation id, and a metric; none produce a 500.
- `/readyz` is red when anything the storefront needs is missing, and the container healthcheck uses it.
- Types are generated, drift is checked in CI; no console errors at 390 px and 1366 px; axe finds no serious violations.
- The image builds reproducibly from pinned dependencies, runs as non-root, and contains no secrets or tests.
- Final report lists, honestly, what was and was not exercised.

## Questions to ask me only if blocked

Ask (one batch, with your recommendation) before: changing GraphRec's public API or plan limits; adding a new infrastructure dependency beyond Redis/Postgres already in the stack; removing the three personas; anything that needs real user accounts or email.

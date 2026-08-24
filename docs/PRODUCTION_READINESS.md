# Production Readiness

`BACKEND_PLAN.md §24`, walked box by box, with the evidence for each one and the
reason for each one that is not ticked.

The section it walks opens with a caveat worth repeating, because it sets what
"ready" means here: *"Given CON-05 this is demonstration-readiness with
production hygiene, not an HA claim."* Nothing below is a claim of high
availability. Every node in §9.1 is a single point of failure and is meant to
be — three hosts, one of each thing, `restart: always` and a rehearsed recovery
rather than a replica.

## How to read this

Each box is one of three things, and the third is the only one that matters:

| | |
|---|---|
| **met** | Implemented, with something automated holding it there. The evidence column names it. |
| **partial** | The part that is done, and the part that is not, both stated. Never a met box with a caveat. |
| **not met** | Not implemented. The reason is written out, not summarised. |

A box is **met** only if something fails when it stops being true. "The code
does this" is not evidence; a test that goes red is. Where the holding thing is
a CI job rather than a test, the job is named.

## Evidence run

Everything below was verified on **2026-08-24** against the working tree at the
close of Phase 16.

```
ruff format --check .          305 files already formatted
ruff check .                   All checks passed!
mypy graphrec apps             Success: no issues found in 166 source files
lint-imports                   Contracts: 3 kept, 0 broken.
pytest                         1285 passed in 132.88s
```

Console: `vitest` 19 files / 123 tests, `tsc --noEmit` clean, `eslint .` 0
errors, `npm run gen:client:check` up to date.

The restore drill was executed rather than described:

```
$ GRAPHREC_SUPERUSER_DATABASE_URL=postgresql://…  scripts/ops/restore_drill.sh
verifying MANIFEST … OK
restoring globals, creating scratch database, restoring dump
checking isolation survived the restore
  rls: ok          35 tables RLS enabled and forced, both sides
  append-only: 0   UPDATE/DELETE grants on usage_events, audit_logs
  migration head:  0014, both sides
PASSED
WARNING: the backup is NOT off-site
```

That warning is part of the result and is carried into the Resilience section
below rather than dropped.

---

## Security

| Box | State | Evidence |
|---|---|---|
| TLS 1.3 on both public surfaces; automatic certificate renewal | **met** | `deploy/n1/Caddyfile` and `deploy/n3/Caddyfile` each carry `tls { protocols tls1.3 }`; `tests/deploy/test_topology.py::test_the_edge_pins_tls_1_3_on_both_public_surfaces` asserts the directive is present *and* names 1.3. Renewal is Caddy's, with no manual step in any runbook — deliberately, since an expired certificate is an outage a calendar reminder is not a control for. |
| Argon2id passwords; EdDSA tokens; JWKS published | **met** | `graphrec/auth/passwords.py` (argon2id, parameters pinned); `graphrec/auth/tokens.py` (Ed25519); `GET /.well-known/jwks.json` in `apps/control_api/routers/well_known.py`; `tests/auth/test_tokens.py`. |
| API credentials HMAC-only at rest, shown once, versioned pepper | **met** | `tests/authz/test_credentials.py`, `tests/authz/test_credential_verification.py`. The plaintext key exists only in the creation response; the row holds an HMAC under a pepper carrying a version, so a pepper rotation is a re-verification path rather than a mass invalidation. |
| RLS `ENABLE` **and `FORCE`** on every tenant table; runtime role is non-owner | **met** | `tests/isolation/test_model_schema_parity.py` walks every mapped table with a `tenant_id` and fails on one that is not both enabled and forced. `tests/isolation/test_runtime_role_privileges.py` asserts the runtime role is not a superuser, cannot `BYPASSRLS`, cannot create roles, databases or tables, and inherits nothing. Re-verified after restore by the drill above. |
| `usage_events` and `audit_logs` have **no `UPDATE`/`DELETE` grant**; `api_keys` has no `DELETE` | **met** | `tests/audit/test_append_only.py` asserts the refusal from both runtime roles, in both directions, against the live grant table. The restore drill re-checks it on the restored copy, which is where it would otherwise silently be lost. |
| Per-endpoint body limits; rate limits on all five configured classes | **met** | Body limits: `tests/ingestion/test_bounds.py`, plus `request_body { max_size 32MB }` at the N1 edge as the outer bound that stops a large body reaching Python at all. Rate limits: `graphrec/http/rate_limit.py`, wired at nine routes, and `tests/api/test_rate_limits.py` — which asserts behaviour *and* walks the route table to prove each of the five classes is attached to something. The second half is the one that matters: until Phase 16 the five settings, the copy string and the 429 mapping all existed and nothing counted a request. |
| Firewall default-deny; databases and storage on private addresses only | **met** | `deploy/firewall/{n1,n3,n2}.nft`; `tests/deploy/test_topology.py` asserts default-deny with forwarding filtered, that nothing but the edge binds a public address, that N2 publishes no port at all, and that every private binding is a WireGuard address. |
| Secrets from files or a store; **none in images, Compose literals or Git** | **met** | `tests/unit/test_secret_files.py` (a mounted file populates the setting, beats a leftover dotenv, loses to the environment); `tests/deploy/test_topology.py::test_secrets_are_mounted_not_passed_as_environment`; `gitleaks` over the full history in the CI security job, because a rotated secret in an old commit is still a published secret. |
| Dependency and image scanning in CI | **met** | `.github/workflows/ci.yml` job `Security scan`: `pip-audit`, `npm audit --audit-level=high`, static analysis, `trivy` over image and filesystem, `gitleaks` over history. Suppressions require a written reason. |
| `.env.example` complete and committed; **real `.env` never committed** | **met** | `.env` is matched by `.gitignore:84`; `gitleaks` over history covers the case where it once was not. Completeness is held by `tests/contract/test_env_example.py`, which compares the file against `Settings.model_fields` in both directions. It was written this phase because the box was not met: fourteen settings had drifted out of the file, among them `POSTGRES_PLATFORM_USER` and `POSTGRES_PLATFORM_PASSWORD` — an operator following `.env.example` would have brought up a deployment where every platform-operator screen connected as a role that deployment never created. |

## Isolation — the gate that matters most

| Box | State | Evidence |
|---|---|---|
| Isolation suite passes and is a **required** merge check | **met** | CI job `Tenant isolation (required)`. It sets `GRAPHREC_REQUIRE_DB=1`, which turns the developer-friendly skip into a failure — a required gate that passes because it found nothing to run reports green and is worse than no gate. |
| Every table carrying `tenant_id` has a corresponding isolation test (CI-enforced) | **met** | `tests/isolation/test_model_schema_parity.py` derives the list from the mapped models rather than from a hand-kept list, so a new tenant table fails the parity test on the commit that adds it. |
| Foreign resources return `404`, never `403` | **met** | `tests/isolation/test_cross_tenant_reads.py`, `tests/isolation/test_lookup_resolvers.py`, and per-resource assertions across the registry, catalogue and platform suites — a `403` confirms the row exists, which is the leak. |
| Gate 4 precedes gate 5, with a test proving it | **met** | `tests/authz/test_gate_order.py`, and CI job `Authorization matrix (required)` runs it under the name "The five gates run in order, and the realms do not meet". |
| Cross-realm token rejection tested both directions | **met** | `tests/authz/test_realm_separation.py`. |
| Bundle manifest `tenant_id` verified before load | **met** | `tests/registry/test_bundle.py`, `tests/serving/test_binding.py`. The key prefix is a convenience; the manifest check is the boundary, because a key is metadata an operator can rename and a manifest is content a digest covers. |

## Correctness

| Box | State | Evidence |
|---|---|---|
| Migrations reversible; up and down tested in CI | **met** | CI job `Migrations apply and reverse`: upgrade, assert the runtime role cannot bypass RLS, downgrade to base, upgrade again. |
| Every accepted job reaches a terminal state or is bounded-retried (ER-NF-01) | **met** | `tests/jobs/test_retry.py`, `tests/jobs/test_lease.py`. A deterministic failure consumes no attempts and is not reclaimed; repeated lease expiry eventually gives up rather than looping. |
| Failed activation demonstrably retains the previous version (ER-F-06) | **met** | `tests/serving/test_activation.py::test_a_failed_activation_leaves_the_previous_version_serving`. |
| Rollback target validated before the active version changes (ER-F-07) | **met** | `tests/serving/test_activation.py::test_rollback_refuses_a_target_that_is_not_the_retained_one` and `::test_rollback_validates_before_it_changes_anything`. |
| Idempotency proven for events, batches, syncs, training and feedback (NR-NF-05, ER-F-04) | **met** | `tests/ingestion/test_ingest_api.py`, `tests/ingestion/test_pipeline.py`, `tests/training/test_admission.py`, and the feedback assertions in `tests/serving/test_inference_api.py`. |
| Recommendation ordering deterministic for identical inputs (ER-NF-06) | **met** | `tests/serving/test_recommendations.py::test_the_same_request_twice_returns_the_same_order`; the fallback lane's own tie-break is asserted separately, since "ordered by popularity" is not a total order and the tail is where it shows. |
| `model_version` and `strategy` in every recommendation response (ER-F-05) | **met** | `tests/serving/test_inference_api.py`, and — since Phase 16 — `tests/serving/test_drills.py`, which asserts the pair is *honest* under a model-store outage. It was not: an unready replica reported `strategy: "personalized"` and `fallback_applied: false` while serving popularity, which meant `FallbackRateHigh` could not fire during exactly the outage it was written for. Fixed in `apps/inference/main.py`. |
| No temporal leakage in the evaluation split | **met** | `tests/ml/test_split.py`. |

## Observability

| Box | State | Evidence |
|---|---|---|
| Structured logs with `request_id` on every line; secrets and payloads never logged | **met** | `graphrec/common/logging.py` (JSON, request id from contextvars); `tests/api/test_error_envelope.py` asserts the identifier appears in the response and the log, and `tests/api/test_health.py::test_a_failed_probe_does_not_leak_connection_details` asserts the DSN does not. |
| Dashboards for host, GPU, API, jobs, training, inference, capacity, business | **partial** | Two dashboards ship: `GraphRec / Platform` (queue depth, oldest queued job, job outcomes, job duration p95, control API latency and errors, metering fallback, build) and `GraphRec / Serving` (ready tenants, request rate, in flight, latency, fallback share, strategy mix, replicas per tenant). That covers **API, jobs, inference and capacity**. **Host is scraped and not drawn** — `node_exporter` is a Prometheus target on all three nodes, so the data is there and no panel reads it. **GPU, training and business are neither scraped nor drawn**: there is no DCGM exporter in the stack, the training worker publishes no per-run series, and no business metric is defined anywhere. `tests/observability/test_dashboards.py` holds what exists to the metrics that are actually published, so nothing on a dashboard is a query that returns no data — it does not assert the eight families exist. |
| Alerts: inference P95 > 300 ms, fallback > 5%, queue depth, job failure rate, disk > 80%, `ready < 1` for an active tenant | **met** | `deploy/observability/alerts.yml`: `InferenceLatencyHigh`, `FallbackRateHigh`, `TenantHasNoReadyReplica`, `JobQueueDeep`, `JobQueueStalled`, `JobFailureRateHigh`, `MeteringDegraded`, `DiskFillingUp`, `TargetDown`. `tests/observability/test_alert_rules.py` checks the thresholds against the numbers in the plan; `tests/observability/test_runbooks.py` checks every alert names a runbook section that exists; `promtool` and `amtool` run in CI. |
| **Measurement gaps reported as gaps, never as zeros** (UC-30) | **met** | `tests/platform/test_measurement_gaps.py`. The counters degrade to the ledger and the console renders a gap rather than a zero, because a zero is a number somebody will act on. |
| Audit written for every action ER-F-11 enumerates | **met** | `tests/audit/`, and ADR 0029 on why a refusal is audited on a second connection — an audit row written inside the transaction that was rolled back is an audit row that does not exist. |

## Resilience

| Box | State | Evidence |
|---|---|---|
| Every failure mode in §9.4 has a documented, rehearsed recovery | **partial** | Documented: `docs/RUNBOOKS.md`, held to the table by `tests/observability/test_runbooks.py`. Rehearsed: `tests/drills/test_failure_posture.py` maps each row to drills that *cause* the failure, and records the three it cannot. Those three are reproduced verbatim below rather than left in a test file. |
| Backups off-site; **restore drill executed and verified** | **partial** | The drill is executed and verified — output above, and `scripts/ops/restore_drill.sh` runs on a systemd timer (`graphrec-restore-drill.timer`) so it is rehearsed rather than remembered. It checks two tiers: row counts across eight tables, and schema facts that fail independently and invisibly — 35 tables with RLS enabled and forced, the migration head, and the absence of `UPDATE`/`DELETE` on the append-only tables. **Off-site is not done.** `scripts/ops/backup.sh` writes to a local directory and prints `NOT off-site` at the end rather than implying otherwise; the copy out is a deployment decision (which provider, which credentials, which retention) that the repository cannot make, and a backup on the machine being backed up is not a backup. |
| Lifecycle rules purge uploads and checkpoints | **partial** | Uploads: `scripts/ops/lifecycle.py` applies `AbortIncompleteMultipartUpload` after one day, bucket-wide — the leak that shows up as a full disk and appears in no listing. Checkpoints and snapshots: **not expired**, and the reason is structural. `graphrec/storage/keys.py` puts the tenant first (`tenants/{tenant_id}/checkpoints/…`), S3 lifecycle filters match a literal prefix with no wildcard, and so no single rule can name "every tenant's checkpoints". The three ways out — tag on write, reorder the keys, or a database-aware sweep — are written out in that script's docstring, along with why the naive age-based sweep is wrong: a checkpoint belonging to a RUNNING job and one belonging to a finished job look identical in the bucket. Checkpoints are bounded only by there being one key per job, overwritten in place. Snapshots are unbounded. |
| Lease expiry recovery demonstrated by killing a worker mid-job | **met** | `tests/jobs/test_lease.py`: the killed worker's job requeues, another worker claims it, and the replaced worker cannot write its result — the third being the one that makes the first two safe. |
| Fallback lane demonstrated with the model store unreachable | **met** | `tests/serving/test_drills.py`. Four assertions: traffic is carried, the replica reports itself unready while it serves, a caller who sets `allow_fallback: false` gets a 503 rather than a stale popularity list, and another tenant's credential is still a 401 — degradation is not a relaxation. |

### The three §9.4 rows that are not drilled

Reproduced from `tests/drills/test_failure_posture.py`, where they are enforced:
a row that is neither drilled nor listed here fails the build.

**N1 down** — Requires three hosts, and the row overstates what this
implementation does: every recommendation lane reads Postgres, which runs on N1,
so with N1 gone N3 returns errors rather than degrading to the popularity lane.
Recorded as a deviation rather than drilled into a pass.

**N3 down** — Requires three hosts. The recovery ("restart; inference reloads
bundles") is the same code path the object-store drills cause at start-up, which
is the part a single process can rehearse.

**Disk exhaustion** — Filling a disk to prove an alert threshold is a drill that
damages the machine it runs on. The alert rule is asserted in
`tests/observability/test_alert_rules.py` and the lifecycle rules that are the
primary defence are asserted in the storage suite — with the gap in those rules
recorded in the Resilience table above.

## Operations

| Box | State | Evidence |
|---|---|---|
| One-command deploy per node; rollback by tag | **met** | `.github/workflows/deploy.yml` with `.github/deploy.sh`, one job per node in the §9.1 order — N1 (migrations first) → N3 (serving, then a reconciler roll) → N2 (training) — with a smoke test between each. Rollback is re-running the workflow at an earlier `GRAPHREC_IMAGE_TAG`; `tests/deploy/test_topology.py::test_no_image_is_floating` refuses a tag that is not pinned, which is what makes "by tag" mean anything. The reconciler roll is a separate step because N3's Compose file does not contain the inference containers — the reconciler owns those, one project per tenant, and a deploy that skipped it would leave the serving fleet on the previous image with nothing saying so. |
| Migrations run before the API starts and are one-release backward-compatible | **met** | `tests/deploy/test_topology.py::test_migrations_run_before_anything_reads_the_schema` asserts the Compose dependency; the deploy workflow orders N1 first for the same reason. Backward compatibility is a review discipline rather than an automated check — see Not done. |
| Runbooks: restore, rotate secrets, evict a stuck job, force a rollback, suspend a tenant | **met** | `docs/RUNBOOKS.md` has all five under `## Procedures`, plus nine incident sections. `tests/observability/test_runbooks.py` holds the file to the alert rules in both directions, so an alert cannot ship without a section and a section cannot outlive its alert. |
| OpenAPI published and matching `/integration`'s documented shapes | **met** | `frontend/openapi.json`, 72 paths, generated by `scripts/gen_openapi.py` as the **merge of both planes** — until Phase 16 it was the control app alone, so the published document did not contain `/v1/recommendations` at all. Every operation names the server that answers it, since N3 routes on the hostname. Held by `tests/contract/test_openapi_document.py` (both planes present; the file is byte-for-byte current) and by `frontend/src/routes/integration/Integration.test.tsx`, which checks every documented row against the document for path, method, host, request fields and response fields. That last check found the page documenting `POST /v1/recommendations/feedback`, a route that does not exist. |
| Demo account bootstrap script (`DEMO_*` settings already exist) | **met** | `scripts/bootstrap_demo.py` — idempotent by lookup, three roles on three connections so the app role's own `WITH CHECK` clause is exercised rather than bypassed. It refuses to run outside local and CI with the published default password; `tests/unit/test_bootstrap_demo.py` asserts that refusal, and asserts that production cannot even construct `Settings` with the shipped defaults, which is the upstream guard. |

## Documentation

| Box | State | Evidence |
|---|---|---|
| `API.md` conflict resolved in writing (§7 Q1) | **met** | `BACKEND_PLAN.md §7.1` and §8. `API.md` is retired as an alternative, explicitly rather than by neglect, and the rescoping (a Personalize-compatible façade over the same core, not a second data model) is written down with the reason: two models model the lifecycle differently, and reconciling them would create two authorities over which model is live. |
| The four SRS defects (§7.2) reported to the supervisor | **not met** | Written up in `BACKEND_PLAN.md §7.2` and unreportable from here. This box asks for a message to a person; the repository can hold the text and cannot send it, and ticking it on the strength of the write-up would be recording an action nobody took. |
| ADRs recorded for Q1–Q12 | **met** | `docs/adr/`, 40 records. D1–D12 are closed; `docs/adr/README.md` carries the index and which were built ahead of confirmation. |
| This plan updated as decisions land | **met** | Phase reports 1–16 in `docs/`, each with what was built, what was verified, what deviated, what earlier bugs it found, and what it did not do. |

---

## Not done, collected

The eight boxes above that are **partial** or **not met**, in one place, because
a list spread across six tables is a list nobody reads:

1. **Off-site backups.** Local backup, verified restore, no copy out.
2. **Lifecycle rules for checkpoints and snapshots.** Multipart aborts only; the
   key layout makes a prefix rule impossible and the alternatives are a change
   to the storage port, a change to the key layout, or a database-aware sweep.
3. **Host, GPU, training and business dashboards.** Host data is scraped and not
   drawn; the other three are not scraped.
4. **The three undrilled §9.4 rows**, reproduced above — and note that **N1
   down** is not a missing drill but a row the implementation does not satisfy.
5. **The four SRS defects** are written up and not reported.
6. **Backward compatibility of migrations** is a review discipline, not a check.
   Nothing runs the previous release against the new schema.
7. **§10.7's design-system question is still open.** The console ships on the
   Modernist tokens the prototype renders with, recorded provisionally as ADR
   0034.
8. **The per-phase "Not done" items** carried from Phases 8–15 remain open and
   are listed in each phase report rather than restated here.

None of these is a surprise at the end. Each is either a decision that needs an
operator's input (1, 3), a piece of work with a real design choice behind it
(2, 6), an action outside the repository (5), a question awaiting an answer (7),
or an honest correction to the plan (4).

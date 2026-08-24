# Phase 16 — Deployment, operations and the readiness checklist

**Scope (BUILD_PROMPT L687-688):** Per-node Compose + systemd (+ k3s profile if
D3 selected it) · CI/CD with ordered deploys (N1 migrations first → N3 inference
→ N2 trainer) and smoke tests between · firewall, private networking, secret
management · backups + a rehearsed restore drill · dashboards and alerts ·
publish OpenAPI and verify it matches the `/integration` page · runbooks ·
failure drills, load test, security scan · walk the `BACKEND_PLAN.md §24`
checklist.

**Gate:** §10.7's design-system question is still unanswered. Asked at Phase 13,
14, 15 and again here. The standing instruction in §10.7 says what to do while
it is open, so the console remains on the Modernist tokens; **ADR 0034** records
that as provisional. Nothing in this phase touched a colour.

**No k3s profile.** D3 chose Compose behind a driver port (**ADR 0028**), so the
conditional in the scope does not apply.

## 1. Built

Three per-node deployments, a deploy pipeline, an observability stack, backup
and restore tooling, ten ADRs, three documents, and — because walking §24 turned
into an audit rather than a tick sheet — four pieces of the platform that the
checklist said existed and did not.

### The estate

`deploy/`, one directory per node, matching §9.1 exactly.

| | N1 Control | N2 Training | N3 Serving |
|---|---|---|---|
| Public | 443 | **none** | 443 |
| Runs | Caddy, control-api, job-worker ×2, reconciler, Postgres, Redis, Prometheus, Alertmanager, Grafana | training-worker | Caddy, inference ×N, MinIO, docker_proxy |
| Holds state | Postgres, Redis | nothing | MinIO |

**Two public ports on the whole estate.** That is a claim with a number in it,
and a claim like that decays one `ports:` entry at a time — a database published
so a colleague can connect, an exporter published because a scrape was failing.
`tests/deploy/test_topology.py` (44 tests) parses the Compose files and compares
what they bind against what §9.1 permits, rather than trusting a review to catch
it.

Also asserted there: no floating image tags, secrets mounted rather than passed
as environment, every long-running service restarting itself, workers outlasting
their leases, migrations running before anything reads the schema, every private
binding being a WireGuard address, every mounted file existing, and — added this
phase — TLS 1.3 pinned on both edges.

`systemd` units bring each node up at boot and wait for the stack to report
healthy; `graphrec-backup.timer` and `graphrec-restore-drill.timer` schedule the
two operational jobs. `deploy/firewall/*.nft` is default-deny with forwarding
filtered.

### The deploy

`.github/workflows/deploy.yml` with `.github/deploy.sh`. One job per node in the
required order, `needs:` chained, with a smoke test between each: **N1
(migrations first) → N3 (serving, then a reconciler roll) → N2 (training)**.

The roll is its own step and its own program. N3's Compose file does not contain
the inference containers — the reconciler owns those, one project per tenant —
so a deploy without it ends with a new control plane and a serving fleet on last
week's image, and every health check green. `apps/reconciler/roll.py` bumps the
epoch on each live deployment without changing `desired_version_id`, which is
the difference between *serve a different model* and *serve the same model out of
a different container*. **ADR 0046**.

### Observability

`deploy/observability/`: Prometheus with eight scrape jobs, Alertmanager, and
two provisioned Grafana dashboards. Nine alert rules covering §24's six, plus
`JobQueueStalled`, `MeteringDegraded` and `TargetDown`.

`graphrec/observability/` holds the registry and a separate exposition listener
on `METRICS_PORT`, bound to the tunnel rather than served on 443 — the
`graphrec_serving_replicas` gauge is labelled by `tenant_id`, so an unguarded
`/metrics` is a list of every tenant and how large each one is (**ADR 0040**).
Estate-wide gauges have exactly one publisher, the reconciler, because a gauge
is a per-process value and four processes publishing the queue depth is four
series that disagree (**ADR 0041**).

### Backups, and a drill that was run

`scripts/ops/`: `backup.sh`, `restore.sh`, `restore_drill.sh`, `pg_env.sh`,
`smoke.sh`, and `lifecycle.py`.

The drill was executed, not described:

```
verifying MANIFEST … OK
restoring globals, creating scratch database, restoring dump
checking isolation survived the restore
  rls: ok          35 tables RLS enabled and forced, both sides
  append-only: 0   UPDATE/DELETE grants on usage_events, audit_logs
  migration head:  0014, both sides
PASSED
WARNING: the backup is NOT off-site
```

The second tier is the one that matters. A database restored with all its rows
and none of its policies looks completely healthy, serves every request, and
shows each tenant everybody else's catalogue. Checking it requires a role that
bypasses RLS — and so does the backup, because `FORCE ROW LEVEL SECURITY` binds
the owner too. The scripts require that role and refuse rather than working
around it with `ALTER TABLE … NO FORCE` (**ADR 0042**).

### The drills

`tests/serving/test_drills.py` and `tests/drills/test_failure_posture.py`.

**A drill is a test that causes the failure, not a test that asserts near it.**
The serving drills seed an ACTIVE version with no published bundle and then ask
the four questions that matter during a model-store outage: is traffic carried,
does the replica say it is unready while it serves, is a caller who set
`allow_fallback: false` refused rather than served stale, and is another
tenant's credential still a 401. Three of the four failed the first time they
ran, which is section 4.

`test_failure_posture.py` parses §9.4's table and requires every row to be in
`DRILLS` — mapped to test node ids, checked against the source, so a renamed
drill goes red — or in `UNDRILLED` with a written reason. Three rows are
undrilled, and one of them is not a missing drill but a row the implementation
does not satisfy.

### Documents

* **`docs/RUNBOOKS.md`** — nine incident sections and five procedures.
* **`docs/PRODUCTION_READINESS.md`** — §24 walked box by box, 43 boxes, with the
  evidence for each and the reason for each that is not ticked. Eight are
  partial or not met and are collected in one list at the end.
* **`frontend/openapi.json`** — 72 paths, now the merge of both planes.

Each is held by a test that fails when it stops being true, in both directions,
with a floor test under every parser (**ADR 0049**).

### Four things §24 claimed and did not have

Walking the checklist honestly meant implementing rather than annotating:

1. **Rate limiting** (`graphrec/http/rate_limit.py`). Five settings, a copy
   string, a 429 mapping — and nothing counting a request. Now wired at nine
   routes across five classes, keyed on the address before sign-in and on the
   tenant after. It fails open and counts that it did (**ADR 0048**).
2. **The demo bootstrap** (`scripts/bootstrap_demo.py`). The `DEMO_*` settings
   were read by nothing. Idempotent by lookup, three roles on three connections
   so the app role's own `WITH CHECK` clause is exercised rather than bypassed.
3. **TLS 1.3.** Neither Caddyfile had a `tls` directive, so both edges ran
   Caddy's default 1.2 floor.
4. **`.env.example`.** Fourteen settings had drifted out of it, including
   `POSTGRES_PLATFORM_USER` and `POSTGRES_PLATFORM_PASSWORD`.

### Counts

| | |
|---|---|
| Backend tests | 1285 passed (1126 at the close of Phase 15) |
| New test files this phase | `tests/deploy/`, `tests/observability/` (5), `tests/drills/`, `tests/api/test_rate_limits.py`, `tests/contract/test_env_example.py`, `tests/storage/test_lifecycle.py`, `tests/storage/test_s3_probe.py`, `tests/serving/test_drills.py`, `tests/serving/test_roll.py`, `tests/unit/test_secret_files.py`, `tests/unit/test_bootstrap_demo.py` |
| Console tests | 19 files / 123 tests |
| ADRs | 0040–0049 |

## 2. Verified

```
ruff format --check .          305 files already formatted
ruff check .                   All checks passed!
mypy graphrec apps             Success: no issues found in 166 source files
lint-imports                   Contracts: 3 kept, 0 broken.
pytest                         1285 passed in 132.88s
```

Console: `vitest` 19 files / 123 tests, `tsc --noEmit` clean, `eslint .` 0
errors / 4 warnings (all `react-refresh/only-export-components`, on files that
deliberately export a constant next to a component),
`npm run gen:client:check` — "generated client is up to date".

Operationally: `restore_drill.sh` PASSED against a live database (output above);
`lifecycle.py --dry-run` produces the configuration it claims to.

The five gates are green. The drill is green. The checklist is walked, and eight
of its boxes are not ticked — deliberately, in writing.

## 3. Decisions and deviations

**Ten ADRs**, indexed in `docs/adr/README.md`. The three that most change how
the system behaves:

* **ADR 0048 — the rate limiter fails open.** Failing closed on a Redis restart
  refuses every request on `/auth/sign-in`, so nobody can sign in, including
  whoever would have signed in to fix the cache. The exposure during a Redis
  outage is credential stuffing against Argon2id; the alternative escalates a
  cache restart to a full outage.
* **ADR 0047 — the published OpenAPI is the merge of both planes**, with each
  operation naming the host that answers it, because N3 routes on the hostname.
* **ADR 0043 — a mounted secret outranks a `.env`**, reversing
  pydantic-settings' documented order. A leftover `.env` on a production node
  would otherwise silently override every mounted secret, and the symptom is a
  signing key that is not the one being rotated.

**Deviations.**

* **No k3s profile.** D3 chose Compose; the conditional does not apply.
* **The load test is a driver, not a gate.** `tests/serving/test_load.py` drives
  the generator in-process. Numbers from a laptop are not numbers from N3, so it
  proves the harness rather than the budget.
* **The WireGuard addresses are literals**, not variables, because Prometheus
  does not interpolate environment variables and half-parameterised addresses
  are worse than either extreme (**ADR 0044**).
* **The suite clears rate-limit counters between tests** rather than widening the
  limits under `ci`. `TestClient` reports one peer for 1285 tests. Clearing keeps
  the shipped numbers under test; widening would have meant the configuration
  that ships is never the configuration exercised.

## 4. Bugs this phase found in code written earlier

Thirteen. The first six were found by writing the deployment, the rest by
walking §24.

1. **`alertmanager.yml` was mounted and never written.** The Compose file
   referenced a file that did not exist; the container would not have started.
2. **Four Prometheus scrape targets resolved to nothing.** Green-looking
   configuration, silently absent metrics. Now
   `test_every_scrape_target_is_resolvable_from_n1`.
3. **The serving template assumed every backing service was a Compose
   neighbour**, which is false once the replicas run as their own project on a
   shared external network.
4. **`npm run lint` had never existed.** The script was referenced and not
   defined, so the console had never been linted. Adding `eslint.config.js`
   surfaced the four warnings above and several errors, now fixed.
5. **Six pinned dependencies carried advisories**, among them a Starlette where
   `request.url.path` is attacker-controllable through a malformed `Host` header
   — the value the metrics and audit paths read. Pinned above FastAPI's floor.
6. **Six ruff errors in Phase 14/15 test files** that had never been linted.
7. **The published OpenAPI omitted the entire data plane.** 67 paths, no
   `/v1/recommendations`. The contract test that was supposed to hold the
   `/integration` page was checking it against a document with none of the
   endpoints the page exists to describe.
8. **The `/integration` page documented `POST /v1/recommendations/feedback`**, a
   route that has never existed — the real ones are
   `/v1/feedback/{impressions,clicks,conversions}` — and its recommendation
   response example disagreed with `RecommendationResponse` in four fields. This
   is the page a customer copies into their own service.
9. **An unready inference replica reported itself as healthy and personalized.**
   `app.state.candidate_index` is a strategy object that exists from start-up
   and is empty until a bundle is loaded into it, so `_service` handed it over
   unconditionally and `_active_version` fell back to the ACTIVE database row. A
   replica that had loaded nothing answered `strategy: "personalized"`,
   `fallback_applied: false` and a real `model_version`, while serving every item
   from the popularity lane.

   The consequence is worse than the wrong field. `recommendation_requests.fallback`
   is written from that boolean, so the tenant's own fallback rate reads 0% and
   **`FallbackRateHigh` cannot fire during exactly the outage it was written
   for.** The same path ignored `allow_fallback: false` and served the fallback
   anyway. Fixed in `apps/inference/main.py`, gated on `binder.is_ready()`.
10. **The `DEMO_*` settings were read by nothing.**
11. **The five rate-limit settings were enforced by nothing.**
12. **Neither Caddyfile pinned TLS 1.3.** Both ran the 1.2 default.
13. **`.env.example` was missing fourteen settings**, including both
    `POSTGRES_PLATFORM_*` values. An operator following the file would have
    brought up a deployment where every platform-operator screen connected as a
    role that deployment never created. Now held by
    `tests/contract/test_env_example.py` in both directions.

Nine and thirteen are the two worth remembering. Both were invisible to every
test that existed, both looked healthy from outside, and both were found by
asking a question in a form that could fail — causing an outage rather than
asserting near one, and comparing a document against the code rather than
reading it.

## 5. Not done

**From this phase.**

1. **Off-site backups.** Local backup, verified restore, no copy out.
   `backup.sh` prints `NOT off-site` rather than implying otherwise. Which
   provider, which credentials and which retention is a deployment decision the
   repository cannot make.
2. **Lifecycle rules for checkpoints and snapshots.** `lifecycle.py` aborts
   incomplete multipart uploads bucket-wide — the leak that presents as a full
   disk and appears in no listing. It cannot expire checkpoints: `keys.py` puts
   the tenant first, S3 lifecycle filters match a literal prefix with no
   wildcard, and so no single rule names "every tenant's checkpoints". The three
   ways out are written in that script's docstring, along with why the naive
   age-based sweep is wrong — a checkpoint belonging to a RUNNING job and one
   belonging to a finished job look identical in the bucket.
3. **Host, GPU, training and business dashboards.** Host is scraped and not
   drawn. The other three are not scraped: no DCGM exporter, no per-run training
   series, no business metric defined anywhere.
4. **§9.4's "N1 down → recommendations continue degraded" is not achievable as
   implemented.** Every recommendation lane reads Postgres, which runs on N1, so
   with N1 gone N3 returns errors rather than degrading to the popularity lane.
   Recorded as a deviation in `UNDRILLED` rather than drilled into a pass. It is
   a correction to the plan, not a task.
5. **"N3 down" and "Disk exhaustion" are undrilled**, for reasons written out in
   the ledger — the first needs three hosts, the second damages the machine it
   runs on.
6. **Backward compatibility of migrations is unchecked.** ADR 0045's ordered
   deploy rests on the new schema serving the old code, and nothing runs the
   previous release against it. This is the single assumption the deploy order
   depends on.
7. **The four SRS defects are written up and not reported.** §24 asks for a
   message to a person; the repository can hold the text and cannot send it.
8. **The load test proves the harness, not the budget.** A 300 ms P95 claim needs
   N3.
9. **`METRICS_ENABLED=false` is a way to run blind.** Nothing alerts on the alert
   pipeline being switched off — `TargetDown` fires on a target that is scraped
   and failing, not on one that never appeared.

**Carried forward, still open.** Workflow tests mock the HTTP boundary; theme
contrast unproven by machine; no platform-operator self-service recovery;
`/admin/usage` unpaginated; two deferred tenant-layout badges; the 15-minute
training cooldown still provisional; no retention sweep for orphaned artifacts;
training concurrency per tenant rather than platform-wide; the metric floor not
tenant-configurable; the training worker on the in-memory counter default; the
reconciler serial and scheduled by nothing but its own loop; `serving_replicas`
rows never swept; no audit retention or partitioning; `security_events` has no
alerting; recovery timing not equalised; invitation rows accumulate per resend;
no cancel route for non-training job types.

**Still unanswered.** §10.7's design-system question, asked in four consecutive
phases.

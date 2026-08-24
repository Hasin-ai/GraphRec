# Runbooks

The procedures an operator runs at 03:00, written for someone who did not build
this and is not going to read the source first.

Every alert in `deploy/observability/alerts.yml` links to a section here by
anchor, and `tests/observability/test_alert_rules.py` fails if a link points at
a heading that does not exist — a runbook reference into nothing is worse than
no reference, because it costs the reader the minute it takes to find out.

Each section is in the same order: **what fired**, **what it means**, **check
this first**, **what to do**, **what not to do**. The last one is there because
most of these have an obvious action that makes the incident worse.

Conventions used below:

* `$API` is the control API's base URL, `$TOKEN` a platform-operator access
  token. Everything an operator does here goes through the API rather than
  through `psql`, for the reason §12 gives: an action taken in the database
  writes no audit row, and the audit trail is the only record of who did what.
* Where `psql` genuinely is the tool — reading, never writing — the connection
  is `$GRAPHREC_OWNER_DATABASE_URL` with the SQLAlchemy `+psycopg` stripped.
  See `scripts/ops/pg_env.sh`.
* Nodes are N1 (control), N2 (training), N3 (serving and storage), per §9.1.

---

## Incidents

### Inference is slow

**What fired.** `InferenceLatencyHigh`. P95 of
`graphrec_http_request_duration_seconds{app="inference"}` above 300 ms for ten
minutes.

**What it means.** The SRS budget is 300 ms and the histogram has a bucket
boundary exactly there, so this is a real crossing rather than an artefact of
where the buckets fall. The alert is a warning, not a page: recommendations are
being served, just slowly.

**Check this first**, in this order, because they have different fixes:

1. `sum by (le) (rate(graphrec_http_request_duration_seconds_bucket{app="inference"}[5m]))` —
   is the whole distribution shifted, or is there a tail? A shifted
   distribution is capacity. A tail is one tenant or one slow dependency.
2. `graphrec_recommendations_total{degraded="true"}` — if the fallback lane is
   also carrying traffic, read
   [the fallback lane is carrying traffic](#the-fallback-lane-is-carrying-traffic)
   instead. The fallback path is not the slow path, so if both fired the
   fallback is a symptom of the same cause, not the cause.
3. `graphrec_http_requests_in_flight{app="inference"}` — flat at a ceiling means
   the process is saturated and the queue is in front of it, not inside it.
4. N3's CPU and disk. Inference reads its bundle from local disk; an artifact
   sweep or a training checkpoint filling the volume shows up here first.

**What to do.**

* Saturation: raise the replica count for the affected tenant and let the
  reconciler converge. It runs a pass every tick and is idempotent.
* One tenant's tail: look at that tenant's catalogue size and its active model
  version. A model version activated against a much larger catalogue changes
  the shape of every request, and the fix is a rollback
  ([force a rollback](#force-a-rollback)), not a restart.
* Nothing conclusive: this is a warning with a ten-minute `for`. It is
  legitimate to leave it until the morning and open a capacity ticket.

**What not to do.** Do not restart the inference process to "clear" it. The
bundle is rebound on start, which means the first requests after a restart are
served by the fallback lane, which turns a latency warning into a quality
incident.

---

### The fallback lane is carrying traffic

**What fired.** `FallbackRateHigh`. More than 5% of responses in fifteen minutes
had `degraded="true"`.

**What it means.** `degraded` is not the same as `strategy="popularity"`. A cold
user served popularity is the system working as designed and is not counted
here. `degraded="true"` means the personalised path was attempted and could not
be taken — the model store was unreachable, the bundle failed to bind, or the
version the deployment names is not on disk.

**Check this first.**

1. `graphrec_inference_ready` — a tenant sitting at `0` names itself.
2. The inference process's logs for `rebind_failed`. The reason is in the log
   line; it is not in the metric, deliberately.
3. Whether a deploy or an activation happened in the last hour. `GET
   $API/v1/deployment` returns the current state and `recent_actions`, which is
   the last few `deployment_revisions` rows with their times.

**What to do.**

* Bundle missing on N3: object storage is the source of truth, N3's disk is a
  cache. Confirm N3 can reach the bucket (`/readyz` on the control API reports
  `object_storage`), then restart the binder so it re-fetches.
* Activation pointed at a version whose artifacts were never uploaded: roll back
  ([force a rollback](#force-a-rollback)). Activation records an intention and
  returns 202; it does not verify the objects exist, which is exactly this
  failure mode.
* Every tenant degraded at once: this is object storage, not the models. Treat
  it as a storage incident.

**What not to do.** Do not silence this on the grounds that responses are still
200. They are — with recommendations that are not the ones the customer is
paying for. This is the alert most likely to be mistaken for a non-incident.

---

### A tenant has no ready replica

**What fired.** `TenantHasNoReadyReplica`. `graphrec_serving_replicas{state="ready"} < 1`
while `desired > 0`, for five minutes. Critical.

**What it means.** The deployment wants replicas and none are ready. The
`desired > 0` half of the expression is what keeps a suspended tenant, or one
that has never deployed, out of this alert.

**Check this first.**

1. Is the reconciler running at all? If `TargetDown` also fired for the
   `reconciler` job, read [a target is down](#a-target-is-down) first: these
   gauges are published by the reconciler, and a dead reconciler reports the
   last values it ever saw, forever.
2. `SELECT revision, kind, status, failure_reason FROM deployment_revisions
   WHERE tenant_id = '…' ORDER BY revision DESC LIMIT 5;`
3. Whether the tenant was suspended: a suspended tenant should have `desired`
   driven to zero, and if it has not, that is the bug rather than the replica.

**What to do.**

* A revision stuck in a non-terminal state: the reconciler is either not
  running or not electing a leader. Check that exactly one process holds the
  advisory lock; two standbys both waiting is normal, zero holders is not.
* A revision with a `failure_reason`: fix what it says, then roll back
  ([force a rollback](#force-a-rollback)) so the tenant is served by the last
  version that worked while you do.
* Nothing wrong with the revision: N3 capacity. Recommendations for this tenant
  are being refused or served by fallback in the meantime.

**What not to do.** Do not `UPDATE serving_replicas` to make the alert stop. The
row is the reconciler's output, not its input; it will be overwritten on the
next pass and you will have removed the only signal.

---

### The job queue is backing up

**What fired.** `JobQueueDeep`. More than fifty `queued` jobs of one type for
fifteen minutes.

**What it means.** Depth alone does not distinguish a busy queue from a stuck
one. That is why there are two rules: this one, and `JobQueueStalled` on the age
of the oldest job. **If both fired, use
[evict a stuck job](#evict-a-stuck-job) instead** — depth is the symptom there,
not the problem.

**Check this first.**

1. `graphrec_job_queue_oldest_seconds{job_type="…"}` — falling means it is
   draining and this is capacity, flat or rising means it is stuck.
2. `rate(graphrec_jobs_finished_total{job_type="…"}[15m])` — zero completions
   with a deep queue means nothing is claiming.
3. `graphrec_job_duration_seconds` — a queue that is draining, slowly, because
   each job now takes ten times as long is a different incident from a queue
   with too few workers.

**What to do.**

* Draining, too slowly: add a worker on N2. The lease makes this safe at any
  time — a claim is a row-level lock with an expiry, so a new worker cannot
  take a job another one holds.
* Ingestion specifically: a single large submission expands into many items.
  This is expected and self-resolving; note the customer and move on.
* Training specifically: concurrency is limited per tenant, so one tenant
  cannot starve the others, and a deep training queue with active workers is
  usually one tenant submitting repeatedly.

**What not to do.** Do not delete queued rows to bring the number down. Every
row is work a customer asked for, and a deleted ingestion job is data that never
arrives with no record that it was dropped.

---

### Evict a stuck job

**What fired.** `JobQueueStalled`. A job has been queued or leased for more than
thirty minutes without finishing. Critical.

**What it means.** Either nothing is claiming the job, or something claimed it
and died holding the lease. Those look identical on the depth gauge and are
distinguished by `lease_owner`.

**Check this first.**

```sql
SELECT job_id, job_type, status, attempt, max_attempts,
       lease_owner, lease_expires_at, started_at
FROM jobs
WHERE status IN ('queued', 'running')
ORDER BY created_at
LIMIT 10;
```

* `status = 'queued'`, no `lease_owner` → nothing is claiming. The worker for
  that type is not running, or `run_after` is in the future.
* `status = 'running'`, `lease_expires_at` in the past → the holder died. **This
  needs no intervention.** An expired lease is reclaimable by design and the
  next worker to poll will take it. Wait one poll interval before acting.
* `status = 'running'`, `lease_expires_at` in the future, `started_at` long ago
  → a live worker is genuinely stuck inside the handler.

**What to do.**

The last case is the only one that needs a human.

1. If it is a training job, request cancellation through the API rather than in
   the database: `POST $API/v1/training-jobs/{training_job_id}:cancel`. This
   sets `cancel_requested_at`, which the handler checks at its own checkpoints.
   Cooperative cancellation is slower than a kill and it leaves the job's own
   cleanup intact.

   **For every other job type there is no cancel route.** Ingestion,
   deployment and evaluation jobs are cancellable in the schema —
   `cancel_requested_at` is on `jobs`, not on `training_jobs` — and nothing
   exposes it. This is a gap, recorded in the Phase 16 report. Until it is
   closed, the only lever for those types is step 2.
2. If the handler never reaches a checkpoint, or there is no cancel route for
   its type, restart that worker process. The
   lease expires and the job is reclaimed with `attempt` incremented, so a job
   that is deterministically fatal will exhaust `max_attempts` and land in
   `failed` rather than looping.
3. If it must not be retried at all, cancel it first, then restart. Cancelling
   after the restart races the reclaim.

**What not to do.** Do not `UPDATE jobs SET status = 'failed'` by hand. It
writes no audit row, skips the failure accounting the metrics are built on, and
leaves whatever the handler had half-written in place.

---

### Jobs are failing

**What fired.** `JobFailureRateHigh`. More than 10% of finished jobs over thirty
minutes ended with `outcome="failed"`.

**What it means.** `failed` here is terminal only. A job that failed twice and
then succeeded is counted `retrying` and does not reach this alert, so this is
not a transient-network alarm — these jobs exhausted their attempts.

**Check this first.**

```sql
SELECT job_type, failure_code, count(*)
FROM jobs
WHERE status = 'failed' AND completed_at > now() - interval '1 hour'
GROUP BY 1, 2 ORDER BY 3 DESC;
```

One `failure_code` dominating is a bug or a dependency. A spread across codes is
usually the platform underneath — disk, storage, or the database.

**What to do.**

* One tenant, one code: almost always their data. The submission errors are
  recorded per row and the customer can see them; this is a support response,
  not an incident.
* Every tenant, one code: this is ours. Roll back the deploy that introduced it.
* Mixed codes: check [disk is filling up](#disk-is-filling-up) and the control
  API's `/readyz`. Jobs fail in many different ways when storage is full.

**What not to do.** Do not requeue in bulk before knowing the code. Re-running
ten thousand jobs that will fail the same way costs an hour and produces the
same alert.

---

### The metering cache is down

**What fired.** `MeteringDegraded`. `graphrec_metering_degraded_total` is
increasing.

**What it means.** Redis is unreachable from at least one process and the usage
counters have fallen back to counting from the ledger. **Every number is still
correct.** The cost is latency on the quota check, which is on the write path.

This alert is not in §24's required six. It is here because it is the failure
that hides: nothing 500s, nothing is wrong on any dashboard, and without this
counter the only symptom is a slow ledger query that nobody attributes.

**Check this first.**

1. Which process. The counter has no label for it on purpose — a per-process
   label on a degradation counter is high-cardinality for no gain — so use
   `up{job="redis"}` and the control API's `/readyz`, which reports Redis as
   `unavailable` rather than `fail` precisely because of this fallback.
2. Whether it is all processes or one. One is a network path; all is Redis.

**What to do.** Restore Redis. There is no data to reconcile afterwards: the
ledger was the source of truth throughout, and the counters re-warm on their
own once the cache answers.

**What not to do.** Do not disable metering to reduce load. The quota check is
what stops a tenant on a small plan from consuming an unbounded amount, and the
usage ledger is what the invoice is computed from.

---

### Disk is filling up

**What fired.** `DiskFillingUp`. A non-tmpfs, non-overlay filesystem is over 80%
full for fifteen minutes.

**What it means.** Almost always N3: artifacts, model bundles and training
checkpoints. The alert filters `tmpfs` and `overlay` because a container host
reports many of those full by design.

**Check this first.**

```
du -sh /var/lib/graphrec/* | sort -h | tail
```

and, in the object store, the bundle prefix. There is currently no retention
sweep for artifacts belonging to superseded model versions — this is a known
gap, recorded in the Phase 15 report — so the usual answer is accumulated
bundles from versions nothing references.

**What to do.**

1. Identify versions that are neither active nor the rollback target:
   ```sql
   SELECT version_id, model_id, created_at FROM model_versions
   WHERE version_id NOT IN (
     SELECT to_version_id FROM deployment_revisions WHERE status = 'succeeded'
     ORDER BY revision DESC LIMIT 2
   );
   ```
2. Delete their artifacts from the object store, not from the local cache. The
   local copy is a cache and will be re-fetched; the object is the copy that
   matters.
3. Never delete the artifacts of the currently active version or of the one
   immediately before it. The second one is what
   [force a rollback](#force-a-rollback) needs to exist.

**What not to do.** Do not extend the volume as the first move without looking
at what is on it. Every previous instance of this alert has been retention, and
a larger disk buys three weeks.

---

### A target is down

**What fired.** `TargetDown`. `up == 0` for five minutes. Critical.

**What it means.** Prometheus cannot scrape a process. This rule exists because
none of the others can fire when the thing they measure has stopped publishing —
an alert set without it reports healthiest during an outage.

**Check this first.** Which job. They fail differently:

| job | what its absence means |
| --- | --- |
| `control_api` | the API is down, or its metrics port is not reachable |
| `inference` | serving is down for at least one tenant; expect `TenantHasNoReadyReplica` shortly |
| `reconciler` | **nothing is converging.** Deployments will sit in non-terminal states and the queue and replica gauges are stale |
| `job_worker` / `training_worker` | nothing is claiming; expect `JobQueueDeep` in fifteen minutes |
| `node` / `postgres` / `redis` | an exporter, not the thing it exports. Check the thing itself before assuming an outage |

**What to do.**

1. Is the process alive? Metrics are served on their own port (9464 by default),
   separate from the application port, so a process can be serving traffic
   perfectly while its metrics port is unreachable — and the reverse.
2. `curl -s localhost:9464/metrics | head` on the node.
3. If the process is alive and the port is not, check the firewall: the metrics
   port is deliberately not published publicly, and a rule that narrowed too far
   will take Prometheus with it.

**What not to do.** Do not restart the process to "fix the scrape" before
confirming the process is the problem. Restarting the reconciler mid-pass is
safe; restarting inference is not (see
[inference is slow](#inference-is-slow)).

---

## Procedures

These are not alerts. They are the operations §24 requires be written down
before they are needed.

### Restore from backup

The rehearsed path. `scripts/ops/restore_drill.sh` runs exactly this against a
scratch database and throws it away, so the procedure below is not a first
attempt.

**Before anything.** You need a connection that bypasses row-level security —
`postgres` on a self-hosted node, the admin role on a managed instance, exported
as `GRAPHREC_SUPERUSER_DATABASE_URL`. `graphrec_owner` will not do: every tenant
table is `FORCE ROW LEVEL SECURITY`, which subjects the owner to the policies
too, and `pg_dump` errors on the first tenant table rather than write a dump
with no rows in it. That refusal is the design working. Do not answer it with
`ALTER TABLE … NO FORCE`.

**Restore into a new database first, always.**

```sh
scripts/ops/restore.sh /backups/20260824T031500Z graphrec_restored
```

The target is a required argument and the script refuses to write over the live
database without `--force`. That is deliberate: a restore is run by someone
tired, and the difference between recovering production and destroying it is one
word on the command line.

The script, in order: verifies the manifest checksums (a truncated transfer
fails here, before anything is dropped), restores roles and grants from
`globals.sql`, creates the target and restores the dump with `--exit-on-error`,
then checks that every `tenant_id`-bearing table came back with RLS **enabled
and forced** and that `graphrec_app` holds no `UPDATE` or `DELETE` on
`usage_events` or `audit_logs`.

That last step is the one that makes this a restore rather than a file copy. A
database restored with all its rows and none of its policies looks completely
healthy, serves every request, and shows each tenant everybody else's
catalogue.

**Then cut over.** Compare counts against what you expect, point the application
at the restored database, and only then consider what to do with the original.
Keep the original. It is the only artifact an investigation has.

**Artifacts are separate.** `artifacts.tar` in the backup directory, or the
object store's own versioning. A backup with `artifacts.MISSING` in it restores
a registry that references objects which do not exist — activation will refuse
rather than serve, which is correct and is also not a working platform.

### Rotate a secret

Different secrets, different procedures. They are not interchangeable.

**A tenant's API credential.** `POST $API/v1/api-keys/{key_id}:rotate`. The key
keeps its identity, its name and its place in the list; only the secret and the
visible prefix change. `grace_seconds` defaults to `0`, which means requests
using the old secret start failing immediately — that is what the console
promises, so do not change it silently. A caller who asks for a window gets one,
capped at 24 hours, during which both secrets authenticate. A second rotation
inside an open window closes it rather than extending it.

**The API key pepper** (`api_key_hmac_pepper`). This one has no rotation
procedure and that is a design consequence, not an oversight: stored hashes are
peppered, so changing it invalidates every credential on the platform at once.
Treat a compromised pepper as an incident requiring every tenant to rotate.

**The JWT signing key.** Ed25519, published through JWKS. Add the new key
alongside the old, let both appear in the JWKS document until every issued token
has expired (access tokens are 15 minutes; refresh sessions are longer and are
the constraint), then remove the old. Removing it first logs everyone out.

**The audit hash secret.** The audit chain is computed with it. Rotating it
breaks verification of everything written before the rotation. If it must be
rotated, record the changeover time and treat the chain as two chains.

**Database and object-store passwords.** Change in the secret store, then
restart the services on all three nodes in deploy order — N1, N3, N2. There is
no in-place reload.

Production refuses to start carrying any of the shipped default secrets
(`Settings._production_requires_real_secrets`), so a rotation that lands a
placeholder fails loudly at boot rather than quietly at runtime.

### Force a rollback

```sh
curl -X POST "$API/v1/models/{model_id}:rollback" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"reason": "…"}'
```

**It returns 202, and 202 does not mean anything is serving yet.** The write
records an intention: a `deployment_revisions` row and a new desired state. The
reconciler converges to it on a later pass, and the fact that it worked is a
separate, later record against the same revision number.

So the procedure has three steps, not one:

1. `POST :rollback` with a reason. The reason is required, it is the only part a
   human writes, and it is what the audit row is worth reading for.
2. Watch the revision reach a terminal state: `GET $API/v1/deployment`, whose
   `recent_actions` carries the revision number this rollback was given.
3. Confirm from the metrics, not from the API:
   `graphrec_inference_ready{tenant_id="…"}` back at `1` and
   `graphrec_recommendations_total{degraded="true"}` flat.

Rolling back needs the previous version's artifacts to still exist. See
[disk is filling up](#disk-is-filling-up) for why they must not be swept.

### Suspend a tenant

```sh
curl -X POST "$API/v1/platform/tenants/{tenant_id}:status" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"status": "suspended", "reason": "Non-payment, escalated twice."}'
```

The reason is required and a short one is refused. The status, the actor and the
time are all mechanical; the reason is the only thing a person contributes, and
it is what the next operator reads.

**What suspension does.** Serving stops — desired replicas go to zero and the
reconciler converges. The console remains reachable so an administrator can see
why. Data is retained; suspension is not deletion and there is no path from one
to the other in this API.

**What to check afterwards.** `graphrec_serving_replicas{tenant_id="…"}` should
show `desired` at zero within a pass or two. If it does not, the reconciler is
not converging and `TenantHasNoReadyReplica` will fire for a tenant that is
supposed to have none — read [a target is down](#a-target-is-down).

Reversing it is the same call with `"status": "active"` and its own reason. The
tenant's previous deployment is re-converged; nothing needs to be reactivated by
hand.

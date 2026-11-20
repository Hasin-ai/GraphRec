# Operating GraphRec

Day-to-day running of a production deployment started as in `docs/DEPLOYMENT.md`.
All commands run from the repository root; `dc` below stands for
`docker compose -f docker-compose.yml -f docker-compose.prod.yml`.

## Health

| Check | Meaning |
|---|---|
| `GET /healthz` | the API process answers and reaches PostgreSQL |
| `GET /readyz` | per-dependency status: `ready`, `degraded` (Redis or Qdrant down; service continues), `not_ready` (database down, 503) |
| Console → Platform Status (`/admin/status`) | database, worker, rate limiter and serving capacity |

What degraded means in practice (tested in `tests/integration/test_fallback_chaos.py`):

- **Qdrant down**: personalized recommendations keep working; the model's item
  table is scored in the API process (slower on large catalogs).
- **Redis down**: rate limits and serving slots fall back to a bounded per-process
  window; `/readyz` and the platform status say `degraded`, and
  `graphrec_rate_limiter_fail_open_total` counts the affected decisions.
- **Model artifact unreadable**: requests are served from tenant popularity, and the
  response does not claim a model version (`model_version_id: null`).
- **Database down**: the API answers 503 with the standard error envelope.

## Metrics

With `METRICS_TOKEN` set, Prometheus on the internal network scrapes
`http://api:8000/metrics` (Caddy refuses `/metrics` publicly):

```yaml
scrape_configs:
  - job_name: graphrec
    authorization: { credentials: "<METRICS_TOKEN>" }
    static_configs: [{ targets: ["api:8000"] }]
```

| Metric | Use |
|---|---|
| `graphrec_http_requests_total{method,route,status}` | traffic and error rate per route template (`status` is `2xx`…`5xx`) |
| `graphrec_http_request_duration_seconds` (histogram, per route) | latency SLOs; alert on p95 of `/v1/recommendations` |
| `graphrec_training_jobs{status="queued"\|"running"}` | queue depth; a growing queue with nothing running means the worker is down |
| `graphrec_tenants{status}`, `graphrec_active_model_versions` | platform size |
| `graphrec_database_up`, `graphrec_rate_limiter_degraded`, `graphrec_rate_limiter_fail_open_total` | dependency state |
| `graphrec_metrics_shared` | 1 when counters are summed over all API processes (Redis up) |

Suggested alerts: `graphrec_database_up == 0` (page); 5xx rate above 1 % for 5
minutes; `graphrec_rate_limiter_degraded == 1` for 5 minutes; recommendation p95
above 1 s for 10 minutes (see `docs/PERFORMANCE.md` for the measured baseline);
`graphrec_training_jobs{status="queued"} > 0` with `running == 0` for 15 minutes.

## Logs

Production logs are JSON, one object per line, on stdout (`dc logs -f api`). Every
request produces one line with `method`, `route` (template, never ids), `status`,
`duration_ms` and the `correlation_id` that the client also receives in
`X-Correlation-ID` and in every error body. Search by correlation id when a tenant
reports an error reference from the console. Caddy logs are JSON too
(`dc logs caddy`). Configure Docker's log rotation (`/etc/docker/daemon.json`,
`"log-opts": {"max-size": "50m", "max-file": "5"}`).

## Backups and restore

`scripts/backup.sh <dir>` writes a timestamped directory: PostgreSQL dump (custom
format; all tenants, grants and RLS policies), one Qdrant snapshot per collection,
trained models, Caddy's certificates, and `SHA256SUMS`. Redis is not backed up (it
holds only short-lived limiter state). Backups contain every tenant's data:
encrypt them and keep copies off the host.

Restore (destructive, asks for confirmation):

```bash
scripts/restore.sh /var/backups/graphrec/graphrec-20261008T021500Z
```

The `.env` secrets must be the ones in use when the backup was taken. Rehearse a
restore on a spare host at least once per quarter: restore, open `/readyz`, sign
in as an operator, and request a recommendation for a known tenant.

## Data retention (D-21)

`dc run --rm retention` (daily, see DEPLOYMENT step 4) deletes operational rows
past their window; `dc run --rm retention python -m scripts.retention --dry-run`
only counts them.

| Data | Kept |
|---|---|
| Serving request metrics, capacity decisions | 90 days |
| Recommendation records, served lists, feedback | 180 days |
| Ended sign-ins, spent setup and recovery tokens, registration idempotency records | 30 days |
| Security events | 1 year |
| Usage ledger | 25 months (tenants can read 24 months of usage) |
| Catalogs, interaction histories, snapshots, model versions, audit log | for the life of the tenant |

## Common tasks

- **Operators**: Console → Operators (role `operator_admin`). Operators are disabled,
  never deleted, so audit attribution stays intact. A role, status or password
  change signs the operator out everywhere.
- **Suspend a tenant**: Console → Tenants → tenant → Status, with a reason. Members
  can then only see the workspace status page; API keys stop working.
- **Account recovery**: Console → Tenants → tenant → Issue recovery token. The token is
  shown to the operator once; deliver it to the verified account owner out of band.
- **Plans and quotas**: Console → Plans & Quotas. Changes below a tenant's current
  usage need explicit acknowledgement and are recorded with the reason.
- **Stuck training job**: a job whose worker died is reclaimed after its heartbeat
  expires and retried once; check `dc logs worker`. Restarting the worker
  (`dc restart worker`) hands the current job back to the queue.
- **Scale**: raise `WEB_CONCURRENCY` (API processes per container) on a larger
  host; limits stay correct because they live in Redis.

## Rotating secrets

| Secret | Effect of rotating |
|---|---|
| `JWT_SIGNING_SECRET` | every console and operator session ends; users sign in again |
| `API_KEY_HMAC_PEPPER` | every API key stops working; tenants create new keys. Bump `API_KEY_HASH_VERSION` |
| `AUDIT_HASH_SECRET` | new audit and security-event hashes no longer match old ones (history stays readable) |
| `POSTGRES_APP_PASSWORD` | change it in PostgreSQL (`ALTER ROLE graphrec_app PASSWORD …`) and in `.env`, then `dc up -d` |
| `METRICS_TOKEN` | update Prometheus at the same time |

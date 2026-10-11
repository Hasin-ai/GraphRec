# Deploying GraphRec

GraphRec ships as one Docker Compose project. Production runs on a single host
with Caddy in front for automatic HTTPS (decision D-10, D-23). This page is the
complete path from an empty server to a working, TLS-protected deployment.

## What you need

- A Linux host with Docker Engine 24+ and Docker Compose **2.24 or newer**
  (the production overlay uses `!reset`). Reference sizing: 2 vCPU and 8 GB RAM
  handle about 80 storefront requests/second (see `docs/PERFORMANCE.md`); training
  runs on the same CPUs, so give busy deployments 4 vCPU or more.
- A DNS name (for example `graphrec.example.com`) whose A/AAAA record points at the
  host, and inbound ports **80 and 443** open. Caddy obtains the certificate from
  Let's Encrypt on first start.
- Outbound HTTPS from the host (image pulls, certificate issuance).

## 1. Configure

```bash
git clone <your GraphRec repository> graphrec && cd graphrec
cp .env.example .env
```

Edit `.env`. Every value marked **CHANGE** must be replaced; with
`GRAPHREC_ENV=production` the services refuse to start on defaults, placeholders
or secrets shorter than 32 characters. Generate each secret with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

| Setting | Production value |
|---|---|
| `GRAPHREC_ENV` | `production` |
| `POSTGRES_OWNER_PASSWORD`, `POSTGRES_APP_PASSWORD` | two different random values |
| `AUDIT_HASH_SECRET`, `JWT_SIGNING_SECRET`, `API_KEY_HMAC_PEPPER` | three different random values. **Keep them with your backups**: changing one invalidates every session, API key or audit hash made with it |
| `PLATFORM_ADMIN_TOKEN` | a random value, used once to create the first operator (step 3), then remove it |
| `METRICS_TOKEN` | a random value if you scrape `/metrics`; leave empty to disable metrics |
| `GRAPHREC_DOMAIN` | the public host name, e.g. `graphrec.example.com` |
| `ACME_EMAIL` | an address for certificate expiry notices |

Add the last two lines yourself (they are read by `docker-compose.prod.yml`):

```bash
echo "GRAPHREC_DOMAIN=graphrec.example.com" >> .env
echo "ACME_EMAIL=ops@example.com" >> .env
```

Pretrained DGSR checkpoints are optional. To offer checkpoint imports, put each
artifact directory under `./model_artifacts/` (or set `MODEL_ARTIFACT_DIR`).

## 2. Start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Order on first start: PostgreSQL → migrations (`migrate`, forward-only) → Redis and
Qdrant → API (waits for `/readyz`) → scheduler and training worker → console
(nginx) → Caddy. Only Caddy publishes ports; the API, Qdrant and nginx stay on the
internal network.

Check it:

```bash
curl -fsS https://graphrec.example.com/readyz     # {"status":"ready",...}
curl -fsS https://graphrec.example.com/v1/meta    # version and "environment":"production"
```

`/readyz` returns `degraded` (still HTTP 200) when Redis or Qdrant is unreachable
and `not_ready` (503) without the database.

## 3. Create the first platform operator

The bootstrap token can create operators only while no active operator exists.
Either use the command line:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm \
  -e OPERATOR_PASSWORD='<at least 12 characters>' api \
  python -m scripts.create_operator --email ops@example.com --name "Ops Lead"
```

or call `POST /v1/platform/operators` once with `Authorization: Bearer $PLATFORM_ADMIN_TOKEN`.
Then sign in at `https://graphrec.example.com/admin/login`, create the other
operators with the roles they need (`docs/SECURITY.md`), and **remove
`PLATFORM_ADMIN_TOKEN` from `.env`** and restart (`up -d`) so the bootstrap path is
closed.

Tenants register themselves at `https://graphrec.example.com/register`. No email is
sent (decision D-05): the one-time setup link is shown on screen after registration,
and invitations and recoveries work the same way.

## 4. Schedule backups and retention

On the host (crontab of a user in the `docker` group, from the repository root):

```cron
15 2 * * *  cd /srv/graphrec && scripts/backup.sh /var/backups/graphrec >> /var/log/graphrec-backup.log 2>&1
45 3 * * *  cd /srv/graphrec && docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm retention >> /var/log/graphrec-retention.log 2>&1
```

Copy backups off the host. Restores and the retention windows are described in
`docs/OPERATIONS.md`.

## Upgrading

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Take a backup first. Migrations are forward-only and run automatically before the
API starts; the worker hands its current training job back to the queue on
shutdown (it is retried, not lost). To return to an older release, restore the
backup taken before the upgrade (`scripts/restore.sh`), then check out the older
release and start it: an older release cannot run on a database migrated by a
newer one.

## Development

```bash
cp .env.example .env
docker compose up -d --build                 # console on http://localhost:5180
docker compose --profile test run --rm api-test
```

Development binds the console to `FRONTEND_PORT` and the API and Qdrant to
`127.0.0.1` only, enables placeholder training and the full-role bootstrap token.

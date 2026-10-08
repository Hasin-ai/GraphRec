# Deploying Reel Storefront

Reel (`apps/reel-storefront`) is the production-grade reference e-commerce client for GraphRec. It demonstrates a MovieLens film catalogue powered by DGSR graph recommendations, real-time telemetry, shelf diffing, anonymous session personalizations, and proof instruments.

---

## 1. Prerequisites

- **GraphRec Backend:** Healthy running instance (API on `:8010` in dev or behind reverse proxy/TLS in production).
- **Redis (optional but recommended for multi-worker scaling):** Shared state for before/after shelf diffs, impression click attribution, rate limiting, and multi-process Prometheus metrics aggregation.
- **Node.js & Python:** Python 3.11+ and Node 20+ (if building assets locally), or Docker 24+ with Docker Compose 2.24+.

---

## 2. Configuration Settings

Reel configures itself through environment variables or `apps/reel-storefront/.env`.

| Environment Variable | Default / Development | Production Requirement | Purpose |
|---|---|---|---|
| `GRAPHREC_BASE_URL` | `http://localhost:8010` (or `http://api:8000`) | Internal API URL | GraphRec backend base URL. |
| `GRAPHREC_API_KEY` | `gr_live_...` | Required (`gr_live_...`) | Storefront API key scoped for events, recommendations, catalog. |
| `REDIS_URL` | `None` (falls back to memory) | `redis://redis:6379/0` | Enables shared state across multiple Uvicorn workers and restarts. |
| `REEL_PORT` | `5290` | `5290` | Storefront HTTP port. |
| `REEL_ENV` | `development` | `production` | Enables strict production checks (secure cookies, strong secrets). |
| `REEL_SECRET_KEY` | `reel-dev-secret-key-...` | Min 32 random characters | Used to HMAC-sign session cookies (`reel_session`). |
| `REEL_COOKIE_SECURE` | `False` | `True` | Forces HTTPS-only cookies and emits HSTS headers. |
| `REEL_METRICS_TOKEN` | `None` (open in dev) | Secret token | Required Bearer token to scrape `/metrics`. |
| `REEL_RATE_LIMIT_PER_MINUTE` | `120` | `120` - `300` | Sliding window rate limit per client IP. |
| `REEL_BODY_LIMIT_BYTES` | `65536` (64 KB) | `65536` | Strict payload size ceiling preventing memory exhaustion. |
| `REEL_ALLOWED_ORIGINS` | Localhost ports | Storefront domains | Enforced CSRF origin check on state-changing API requests. |
| `REEL_LOG_FORMAT` | `json` | `json` | Structured JSON logs output to stdout. |

---

## 3. Bootstrapping the Reel Tenant

To bootstrap the tenant, register the catalog, seed persona training events, and activate the MovieLens 32M DGSR checkpoint:

```bash
# Development (against local Docker stack):
python apps/reel-storefront/scripts/bootstrap_reel.py \
    --platform-token $PLATFORM_ADMIN_TOKEN

# Custom environment file and base URL:
python apps/reel-storefront/scripts/bootstrap_reel.py \
    --base-url https://api.graphrec.internal \
    --platform-token $PLATFORM_ADMIN_TOKEN \
    --env-file apps/reel-storefront/.env
```

### Idempotency & Safety
- **Tenant Reuse:** By default, if an active Reel tenant already exists and credentials in `.env` are valid, the bootstrap script reuses it without duplicating catalog entries or re-registering.
- **Force Fresh Tenant:** Pass `--new-tenant` to force creating a new tenant with a fresh random suffix.
- **Secret Masking:** API keys, passwords, and tokens are masked (`gr_live_...`) in terminal stdout to prevent log leakage.
- **Teardown:** Pass `--teardown` to mark the Reel tenant suspended and clear local state.

---

## 4. Container Deployment

Reel ships with a hardened, multi-stage Dockerfile:
- Builds frontend assets cleanly via Vite (`npm ci && npm run build`).
- Uses pinned dependencies (`requirements.txt`).
- Runs as an unprivileged non-root user (`reel:reel`, UID 10001).
- Ships with Docker container health checks probing `/readyz`.

```bash
# Build and start container via root compose:
docker compose up -d --build reel

# Verify container health:
docker compose ps reel
```

---

## 5. Verification Checklist

1. **Liveness check:**
   ```bash
   curl -I http://localhost:5290/healthz
   # HTTP/1.1 200 OK
   ```
2. **Deep readiness check:**
   ```bash
   curl -s http://localhost:5290/readyz
   # {"status":"ready","checks":{"graphrec":"ok","redis":"ok","catalogue":"ok","model":"ok"}}
   ```
3. **Security headers check:**
   ```bash
   curl -I http://localhost:5290/
   # Expect Content-Security-Policy, X-Frame-Options: DENY, X-Content-Type-Options: nosniff
   ```
4. **Metrics check:**
   ```bash
   curl -s -H "Authorization: Bearer $REEL_METRICS_TOKEN" http://localhost:5290/metrics
   # Expect reel_http_requests_total, reel_metrics_shared, etc.
   ```

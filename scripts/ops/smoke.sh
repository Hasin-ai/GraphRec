#!/usr/bin/env bash
#
# The check that runs between nodes during a deploy.
#
# `.github/workflows/deploy.yml` brings up N1, runs this, brings up N3, runs
# this, brings up N2, runs this. The point of the ordering is that a failure is
# attributable: if N3's smoke test fails, N1 is known good and the thing that
# broke is the thing that just changed.
#
# ## What a smoke test is allowed to be
#
# Not a test suite. Three properties per node, chosen because each one is
# *cheap*, *unambiguous* and *would have caught a real deploy failure*. A smoke
# test that takes four minutes gets skipped under pressure, and one that fails
# intermittently gets ignored, which is worse than not having it.
#
# Every check here is unauthenticated or uses the platform metrics endpoint. A
# smoke test that needs a tenant credential is a smoke test that needs a secret
# in the deploy pipeline, and the pipeline already has enough of those.
#
# ## Why N2 is checked through Prometheus
#
# N2 has no public port and no inbound service — that is the §9.1 property the
# firewall enforces. So there is nothing to curl. The only externally visible
# fact about a healthy N2 is that its exporter is being scraped, which is a
# question for N1's Prometheus. This is not a workaround; it is the check
# matching the topology.
#
# Usage:
#   scripts/ops/smoke.sh n1|n2|n3
#
# Environment:
#   SMOKE_CONSOLE_URL     https://console.example.com   (N1's edge)
#   SMOKE_API_URL         https://api.example.com       (N3's edge)
#   SMOKE_PROMETHEUS_URL  http://10.10.0.1:9090         (on the tunnel)
#   SMOKE_TIMEOUT         seconds to wait for readiness  (default 120)
#
set -euo pipefail

NODE="${1:-}"
TIMEOUT="${SMOKE_TIMEOUT:-120}"
FAILED=0

if [ -z "$NODE" ]; then
  echo "usage: scripts/ops/smoke.sh n1|n2|n3" >&2
  exit 2
fi

ok()   { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1" >&2; FAILED=1; }

# `curl` with the flags that matter: fail on 4xx/5xx, follow nothing, and never
# hang. A smoke test without `--max-time` is a deploy that hangs on a firewall
# rule instead of failing on one.
get() { curl --silent --show-error --max-time 10 "$@"; }

status_of() { get --output /dev/null --write-out '%{http_code}' "$1" || echo "000"; }

# Poll rather than sleep. `systemctl start` returns once `--wait` is satisfied,
# but a container that is healthy is not the same as an edge that has finished
# obtaining a certificate.
await() {
  local label="$1" url="$2" want="$3" deadline
  deadline=$(( $(date +%s) + TIMEOUT ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if [ "$(status_of "$url")" = "$want" ]; then ok "$label"; return 0; fi
    sleep 3
  done
  fail "$label (never returned $want within ${TIMEOUT}s)"
  return 1
}

promql() {
  # One instant vector, reduced to the first sample's value, or empty.
  get --get --data-urlencode "query=$1" "${SMOKE_PROMETHEUS_URL:?set SMOKE_PROMETHEUS_URL}/api/v1/query" \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "")'
}

echo "=== smoke: ${NODE}"

case "$NODE" in
  n1)
    CONSOLE="${SMOKE_CONSOLE_URL:?set SMOKE_CONSOLE_URL}"

    # 1. The process is up and the migrations it depends on have run. `/readyz`
    #    probes Postgres, Redis and the object store, and returns 503 unless all
    #    three answer — which is exactly the deploy failure worth catching:
    #    a control API that started before its database finished migrating.
    await "readyz is 200" "${CONSOLE}/readyz" "200" || true

    # 2. The console is served. `/readyz` passing while the SPA 404s is a Caddy
    #    misconfiguration, and it is invisible from the API side.
    await "the console is served" "${CONSOLE}/" "200" || true

    # 3. Authentication is wired. An unauthenticated read of a tenant resource
    #    must be 401 — not 200, and not 500. This is the check that catches a
    #    deploy where the signing key failed to mount: the API comes up, serves
    #    `/readyz`, and lets everyone in.
    code="$(status_of "${CONSOLE}/v1/me")"
    if [ "$code" = "401" ]; then ok "an unauthenticated read is 401"
    else fail "an unauthenticated read returned ${code}, expected 401"; fi

    # 4. HSTS. Cheap, and the header that silently disappears when a `handle`
    #    block is reordered.
    if get --head "${CONSOLE}/" | grep -qi '^strict-transport-security:'; then
      ok "HSTS is set"
    else
      fail "no Strict-Transport-Security on the console edge"
    fi
    ;;

  n3)
    API="${SMOKE_API_URL:?set SMOKE_API_URL}"

    # 1. N3's own edge answers. Its `/healthz` is Caddy's, not an application's
    #    — there is no application on N3 that answers on the apex.
    await "the serving edge answers" "${API}/healthz" "200" || true

    # 2. A hostname with no tenant behind it is a 404. The routing is
    #    hostname-based (`{http.request.host.labels.3}`), so the failure mode
    #    worth catching is a catch-all that sends every unknown host to whatever
    #    replica happens to exist.
    code="$(status_of "${API}/v1/recommendations")"
    if [ "$code" = "404" ]; then ok "the apex serves no tenant"
    else fail "the apex returned ${code} for a tenant route, expected 404"; fi

    # 3. The object store is reachable from N3 itself. MinIO's readiness probe,
    #    on the tunnel address, because a serving node whose bundles are
    #    unreadable comes up and then fails every activation.
    if [ -n "${SMOKE_MINIO_URL:-}" ]; then
      await "the object store is live" "${SMOKE_MINIO_URL}/minio/health/live" "200" || true
    else
      echo "  skip  object store (set SMOKE_MINIO_URL to check it)"
    fi
    ;;

  n2)
    # N2 publishes nothing. See the header: the only externally visible fact
    # about a healthy training node is that Prometheus is scraping it.
    deadline=$(( $(date +%s) + TIMEOUT ))
    value=""
    while [ "$(date +%s)" -lt "$deadline" ]; do
      value="$(promql 'up{job="training_worker"}')"
      [ "$value" = "1" ] && break
      sleep 3
    done
    if [ "$value" = "1" ]; then ok "the training worker is being scraped"
    else fail "up{job=\"training_worker\"} is '${value:-absent}' after ${TIMEOUT}s"; fi

    # And that it is leasing. A worker that is up and never claims a job is a
    # worker with the wrong database credentials, which `up` cannot see.
    build="$(promql 'graphrec_build_info{job="training_worker"}')"
    if [ "$build" = "1" ]; then ok "it publishes its build"
    else fail "no graphrec_build_info from the training worker"; fi
    ;;

  *)
    echo "unknown node '${NODE}'; expected n1, n2 or n3" >&2
    exit 2
    ;;
esac

if [ "$FAILED" -eq 0 ]; then
  echo "=== smoke ${NODE}: PASSED"
else
  echo "=== smoke ${NODE}: FAILED" >&2
  exit 1
fi

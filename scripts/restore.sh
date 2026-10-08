#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh onto a host with the same .env secrets
# (JWT_SIGNING_SECRET, API_KEY_HMAC_PEPPER and AUDIT_HASH_SECRET must match the
# backup, or every session, API key and audit hash becomes invalid).
#
#   scripts/restore.sh /var/backups/graphrec/graphrec-20261008T020000Z
#
# DESTRUCTIVE: replaces the database, vector collections, trained models and
# certificates of this deployment. It asks for confirmation unless --yes is given.
set -euo pipefail

SRC="${1:?usage: scripts/restore.sh <backup directory> [--yes]}"
CONFIRM="${2:-}"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
(cd "$SRC" && sha256sum --check --quiet SHA256SUMS)
if [[ "$CONFIRM" != "--yes" ]]; then
  read -r -p "Replace ALL data of this deployment with $SRC? Type 'restore' to continue: " answer
  [[ "$answer" == "restore" ]] || { echo "Aborted."; exit 1; }
fi
# shellcheck disable=SC1091
set -a; source .env; set +a
project="$("${COMPOSE[@]}" config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"

echo "Stopping application services"
"${COMPOSE[@]}" stop caddy frontend api scheduler worker
"${COMPOSE[@]}" up -d postgres qdrant redis

echo "PostgreSQL"
"${COMPOSE[@]}" exec -T postgres dropdb -U "$POSTGRES_OWNER_USER" --if-exists --force "$POSTGRES_DB"
"${COMPOSE[@]}" exec -T postgres createdb -U "$POSTGRES_OWNER_USER" "$POSTGRES_DB"
"${COMPOSE[@]}" exec -T postgres pg_restore -U "$POSTGRES_OWNER_USER" -d "$POSTGRES_DB" --exit-on-error < "$SRC/postgres.dump"

echo "Trained models and certificates"
for volume in trained_models caddy_data; do
  docker run --rm -v "${project}_${volume}:/data" -v "$SRC:/backup:ro" alpine:3.20 \
    sh -c "find /data -mindepth 1 -delete && tar -xzf /backup/${volume}.tgz -C /data"
done

echo "Qdrant collections"
"${COMPOSE[@]}" run --rm --no-deps -v "$SRC/qdrant:/restore:ro" api python - <<'PY'
import pathlib, urllib.request
from graphrec_core.settings import get_settings
base = get_settings().qdrant_url.replace(":6334", ":6333")
for snapshot in sorted(pathlib.Path("/restore").glob("*.snapshot")):
    name = snapshot.stem
    boundary = "graphrecrestore"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"snapshot\"; filename=\"{snapshot.name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + snapshot.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(f"{base}/collections/{name}/snapshots/upload?priority=snapshot", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(request).read()
    print("restored", name)
PY

echo "Starting the stack (migrations run first)"
"${COMPOSE[@]}" up -d
echo "Restore complete. Check: curl -fsS https://\$GRAPHREC_DOMAIN/readyz"

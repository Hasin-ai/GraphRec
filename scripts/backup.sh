#!/usr/bin/env bash
# Back up a production GraphRec host (Phase 5). Run from the repository root:
#
#   scripts/backup.sh /var/backups/graphrec
#
# Writes one timestamped directory with:
#   postgres.dump      pg_dump custom format (all tenants, roles' grants, RLS policies)
#   qdrant/            one snapshot per collection (item embeddings per model version)
#   trained_models.tgz trained model artifacts (the model registry points at these)
#   caddy_data.tgz     TLS certificates and ACME account
#   SHA256SUMS         checksums of everything above
# Redis is not backed up: it holds only short-lived rate-limit windows and slot leases.
# Keep backups off the host and encrypted; they contain every tenant's data.
set -euo pipefail

DEST_ROOT="${1:?usage: scripts/backup.sh <destination directory>}"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${DEST_ROOT%/}/graphrec-${STAMP}"
mkdir -p "$DEST/qdrant"
umask 077

# shellcheck disable=SC1091
set -a; source .env; set +a

echo "PostgreSQL -> $DEST/postgres.dump"
"${COMPOSE[@]}" exec -T postgres pg_dump -U "$POSTGRES_OWNER_USER" -d "$POSTGRES_DB" --format=custom \
  > "$DEST/postgres.dump"

echo "Qdrant snapshots -> $DEST/qdrant/"
collections="$("${COMPOSE[@]}" exec -T api python - <<'PY'
from graphrec_core.vector_store.client import get_qdrant_client
print("\n".join(c.name for c in get_qdrant_client().get_collections().collections))
PY
)"
for collection in $collections; do
  "${COMPOSE[@]}" exec -T api python - "$collection" <<'PY' > "$DEST/qdrant/${collection}.snapshot"
import sys, urllib.request
from graphrec_core.settings import get_settings
from graphrec_core.vector_store.client import get_qdrant_client
name = sys.argv[1]
snapshot = get_qdrant_client().create_snapshot(collection_name=name)
base = get_settings().qdrant_url.replace(":6334", ":6333")
with urllib.request.urlopen(f"{base}/collections/{name}/snapshots/{snapshot.name}") as response:
    sys.stdout.buffer.write(response.read())
PY
done

echo "Trained models and certificates"
project="$("${COMPOSE[@]}" config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
for volume in trained_models caddy_data; do
  docker run --rm -v "${project}_${volume}:/data:ro" -v "$DEST:/backup" alpine:3.20 \
    tar -czf "/backup/${volume}.tgz" -C /data .
done

(cd "$DEST" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
echo "Backup complete: $DEST"

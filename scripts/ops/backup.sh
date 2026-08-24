#!/usr/bin/env bash
#
# Take a backup: the database, the object store, and a manifest that proves
# what was taken.
#
# Three properties, in the order they matter.
#
# 1. **The manifest is checksummed.** A backup nobody has verified is a belief,
#    not a backup. `restore.sh` recomputes these before it restores anything,
#    so a truncated transfer fails at the start of the drill rather than in the
#    middle of an incident.
# 2. **`pg_dump -Fc`, not `-Fp`.** The custom format restores in parallel, can
#    restore a single table, and — the reason that matters here — carries the
#    object list, so `pg_restore -l` can answer "is the `usage_events` table in
#    this file" without restoring it.
# 3. **Roles and grants are dumped separately.** `pg_dump` does not include
#    them, and this platform's isolation guarantee *is* its grants: a database
#    restored without `graphrec_app`'s row-level policies is a database where
#    every tenant can read every other one. `pg_dumpall --globals-only` is not
#    optional here.
#
# 4. **It runs as an RLS-bypassing role, and refuses otherwise.** Not the
#    owner: every tenant table is FORCE'd, so `pg_dump` as `graphrec_owner`
#    errors on the first one. `require_rls_bypass` says so up front rather than
#    letting that surface as a confusing failure halfway through.
#
# Off-site is a matter of where BACKUP_DIR points. It is left as a mount rather
# than an `aws s3 cp` in this script, because the destination is a deployment
# decision and a script that hard-codes one is a script that quietly stops
# copying when it changes.
#
# Usage:
#   scripts/ops/backup.sh [destination]
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BACKUP_ROOT="${1:-${BACKUP_DIR:-var/backups}}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_ROOT}/${STAMP}"

# shellcheck source=scripts/ops/pg_env.sh
. "${ROOT}/scripts/ops/pg_env.sh"
require_client
# Before anything is written, not after half a dump exists. See `pg_env.sh`:
# the owner role cannot read its own tenant tables, by design.
require_rls_bypass

ARTIFACT_ROOT="${ARTIFACT_LOCAL_ROOT:-var/artifacts}"
MINIO_ALIAS="${MINIO_ALIAS:-}"
MINIO_BUCKET="${S3_BUCKET:-graphrec}"

mkdir -p "$DEST"
echo "backup: ${DEST}"

# --- the database ----------------------------------------------------------

echo "  pg_dump ${LIVE_DB}"
# On $BACKUP_URL, not $PGURL. The owner cannot read past FORCE'd RLS.
pg_dump "$BACKUP_URL" --format=custom --compress=6 --file "${DEST}/database.dump"

# Roles, grants and policies. See the header: without these the restore is a
# database with no isolation.
echo "  pg_dumpall --globals-only"
pg_dumpall --dbname "$BACKUP_ADMIN_URL" --globals-only > "${DEST}/globals.sql"

# --- the object store ------------------------------------------------------
#
# Artifacts, checkpoints and bundles. Copied with `mc mirror` where the client
# is available and skipped loudly where it is not — an object store backup that
# silently did nothing is the failure this whole file exists to prevent.

if [ -n "$MINIO_ALIAS" ] && command -v mc >/dev/null 2>&1; then
  echo "  mc mirror ${MINIO_ALIAS}/${MINIO_BUCKET}"
  staging="$(mktemp -d)"
  mc mirror --quiet "${MINIO_ALIAS}/${MINIO_BUCKET}" "$staging"
  tar -C "$staging" -cf "${DEST}/artifacts.tar" .
  rm -rf "$staging"
elif [ -d "$ARTIFACT_ROOT" ]; then
  echo "  tar ${ARTIFACT_ROOT}"
  tar -C "$ARTIFACT_ROOT" -cf "${DEST}/artifacts.tar" .
else
  # Loudly, and with a file left behind saying so. An artifact backup that
  # silently did nothing is the failure this whole script exists to prevent,
  # and `restore.sh` refuses to be quiet about restoring one of these.
  echo "  WARNING: no artifact source found; models and bundles NOT backed up" >&2
  echo "set MINIO_ALIAS (with mc configured) or ARTIFACT_LOCAL_ROOT" > "${DEST}/artifacts.MISSING"
fi

# --- the manifest ----------------------------------------------------------

(
  cd "$DEST"
  for file in *; do
    [ "$file" = "MANIFEST" ] && continue
    printf '%s  %s\n' "$(shasum -a 256 "$file" | cut -d' ' -f1)" "$file"
  done
) > "${DEST}/MANIFEST"

cat > "${DEST}/README" <<INFO
GraphRec backup ${STAMP}
database: ${LIVE_DB} (pg_dump custom format)
globals:  roles, grants and RLS policies (pg_dumpall --globals-only)

Restore with:
    scripts/ops/restore.sh ${DEST} <target-database>

Verify without restoring:
    shasum -a 256 -c ${DEST}/MANIFEST
INFO

echo "  manifest:"
sed 's/^/    /' "${DEST}/MANIFEST"
echo "backup complete: ${DEST}"

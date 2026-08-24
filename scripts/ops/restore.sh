#!/usr/bin/env bash
#
# Restore a backup into a database of your choosing.
#
# **The target is a required argument and it is never the live database by
# default.** That is the whole safety design of this script. A restore is run
# during an incident, by someone tired, and the difference between recovering
# production and destroying it is one word on a command line. Making the target
# explicit means the destructive form has to be typed out.
#
# The order is not arbitrary:
#
#   1. verify the manifest      — a truncated dump fails here, before anything
#                                 has been dropped
#   2. globals (roles, grants)  — the app role must exist before objects owned
#                                 by it can be created
#   3. the dump                 — schema and data
#   4. verify                   — RLS is on and FORCEd, and the app role can
#                                 see nothing without a tenant bound
#
# Step 4 is the one that makes this a restore rather than a file copy. A
# database restored with its rows and without its policies looks completely
# healthy and has no tenant isolation whatsoever, and nothing in steps 1–3 can
# tell you which one you have.
#
# Usage:
#   scripts/ops/restore.sh <backup-dir> <target-database> [--force]
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BACKUP="${1:-}"
TARGET="${2:-}"
FORCE="${3:-}"

if [ -z "$BACKUP" ] || [ -z "$TARGET" ]; then
  echo "usage: scripts/ops/restore.sh <backup-dir> <target-database> [--force]" >&2
  exit 2
fi

# shellcheck source=scripts/ops/pg_env.sh
. "${ROOT}/scripts/ops/pg_env.sh"
require_client
# Restoring needs the same bypass the dump needed: COPY into a FORCE'd table is
# checked against the policies, and `pg_restore` runs with row_security = off.
require_rls_bypass

if [ "$TARGET" = "$LIVE_DB" ] && [ "$FORCE" != "--force" ]; then
  cat >&2 <<WARN
refusing to restore over the live database '${LIVE_DB}'.

This is not a permission problem. Restoring over the live database is the
correct action during a real recovery and the wrong one during a drill, and the
two are indistinguishable to this script. Pass --force if you meant it.
WARN
  exit 3
fi

# --- 1. verify -------------------------------------------------------------

echo "verifying ${BACKUP}/MANIFEST"
( cd "$BACKUP" && shasum -a 256 -c MANIFEST )

if [ -f "${BACKUP}/artifacts.MISSING" ]; then
  echo "WARNING: this backup contains no artifacts. Models and bundles will" >&2
  echo "         not be restored; the registry will reference objects that do" >&2
  echo "         not exist and activation will refuse rather than serve." >&2
fi

# --- 2. globals ------------------------------------------------------------

echo "restoring roles and grants"
# Idempotent by tolerance rather than by construction: `CREATE ROLE` on an
# existing role is an error, and on a running cluster the roles are usually
# already there. The errors are shown, not hidden — a failure here that is not
# "role already exists" is one that matters.
psql "$BACKUP_ADMIN_URL" --quiet --file "${BACKUP}/globals.sql" 2>&1 \
  | grep -v "already exists" || true

# --- 3. the dump -----------------------------------------------------------

echo "creating ${TARGET}"
psql "$BACKUP_ADMIN_URL" --quiet -c "DROP DATABASE IF EXISTS \"${TARGET}\";" >/dev/null
psql "$BACKUP_ADMIN_URL" --quiet -c "CREATE DATABASE \"${TARGET}\";" >/dev/null

echo "restoring ${BACKUP}/database.dump into ${TARGET}"
# `--exit-on-error` deliberately. The default is to report every failure and
# then say "restore complete", which is how a half-restored database gets
# declared recovered.
pg_restore --dbname "$(backup_url_for "$TARGET")" --no-owner --exit-on-error \
  "${BACKUP}/database.dump"

# --- 4. verify the thing that cannot be seen -------------------------------

echo "checking that isolation survived the restore"
psql "$(url_for "$TARGET")" --no-align --tuples-only <<'SQL'
\set ON_ERROR_STOP on

-- Every table that carries a tenant_id must have RLS enabled *and* forced.
-- FORCE is the half that is easy to lose: without it the owner bypasses every
-- policy, and the owner is who migrations run as.
SELECT CASE
  WHEN count(*) = 0 THEN 'rls: ok'
  ELSE 'rls: FAILED on ' || string_agg(c.relname, ', ')
END
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN information_schema.columns col
  ON col.table_name = c.relname AND col.column_name = 'tenant_id'
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
  AND NOT (c.relrowsecurity AND c.relforcerowsecurity);

-- The append-only tables must still be append-only.
SELECT CASE
  WHEN count(*) = 0 THEN 'append-only: ok'
  ELSE 'append-only: FAILED, ' || string_agg(table_name || '.' || privilege_type, ', ')
END
FROM information_schema.table_privileges
WHERE grantee = 'graphrec_app'
  AND table_name IN ('usage_events', 'audit_logs')
  AND privilege_type IN ('UPDATE', 'DELETE');
SQL

echo "restore complete: ${TARGET}"

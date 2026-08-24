#!/usr/bin/env bash
#
# The rehearsal. BACKEND_PLAN §24: "restore drill executed and verified".
#
# A backup script that has never been restored from is a script that produces
# files. This runs the whole path — back up, restore into a scratch database,
# check what came back — and then throws the scratch database away, so it is
# safe to run on a schedule and there is no reason not to.
#
# ## What it checks, and why it is not just row counts
#
# Two tiers, because they fail independently and only one of them is visible.
#
#   rows    tenants, products, interaction_events, usage_events, audit_logs,
#           jobs, model_versions, api_keys. One of each kind of thing:
#           configuration, tenant data, the behavioural stream the models are
#           trained on, the append-only ledger the bill is computed from, the
#           record that has to outlive everything else, queued work, the
#           registry the serving layer reads, and the credentials without which
#           a restored database serves nobody.
#
#   schema  tables, indexes, policies, tables with RLS both enabled *and*
#           forced, the migration head, and the absence of UPDATE/DELETE on the
#           append-only tables. This is the tier that catches the restore
#           failure nobody notices: a database with all of its rows and none of
#           its isolation looks completely healthy, serves every request, and
#           shows each tenant everybody else's catalogue.
#
# Both tiers run as a role that bypasses row-level security, for the reason
# `pg_env.sh` sets out at length — the owner cannot read its own tenant tables,
# and a drill that counted zero rows on both sides would compare equal and
# print PASSED. A verification step that cannot fail is worse than none.
#
# What it does not prove: that an off-site copy exists. A script running on the
# machine being backed up cannot check that, and it is said out loud at the end
# rather than left to be assumed.
#
# Usage:
#   GRAPHREC_SUPERUSER_DATABASE_URL=postgresql://... scripts/ops/restore_drill.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/ops/pg_env.sh
. "${ROOT}/scripts/ops/pg_env.sh"
require_client
require_rls_bypass

SCRATCH="graphrec_drill_$(date -u +%H%M%S)"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
FAILED=0

cleanup() {
  psql "$BACKUP_ADMIN_URL" --quiet -c "DROP DATABASE IF EXISTS \"${SCRATCH}\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ask() {
  # One scalar, from one database, with no decoration.
  psql "$1" --no-align --tuples-only --quiet -c "$2" | tr -d '[:space:]'
}

compare() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ] && [ -n "$expected" ]; then
    printf '    %-28s %-10s == %-10s ok\n' "$label" "$expected" "$actual"
  else
    printf '    %-28s %-10s != %-10s FAILED\n' "$label" "$expected" "$actual"
    FAILED=1
  fi
}

echo "=== restore drill, started ${STARTED}"
echo "    live database: ${LIVE_DB}"
echo

# --- take a backup ---------------------------------------------------------

echo "--- taking a backup"
BACKUP_OUT="$(scripts/ops/backup.sh var/backups/drill)"
BACKUP_DIR="$(echo "$BACKUP_OUT" | awk '/^backup complete: /{print $3}')"
echo "    ${BACKUP_DIR}"
echo

# --- restore it ------------------------------------------------------------

echo "--- restoring into ${SCRATCH}"
scripts/ops/restore.sh "$BACKUP_DIR" "$SCRATCH" | sed 's/^/    /'
echo

# --- the rows --------------------------------------------------------------

echo "--- row counts"
for table in tenants products interaction_events usage_events audit_logs jobs model_versions api_keys; do
  query="SELECT count(*) FROM ${table}"
  compare "$table" \
    "$(ask "$BACKUP_URL" "$query")" \
    "$(ask "$(backup_url_for "$SCRATCH")" "$query")"
done
echo

# --- the schema, and the isolation that rides on it ------------------------

echo "--- schema fidelity"

TABLES="SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
INDEXES="SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'"
POLICIES="SELECT count(*) FROM pg_policies WHERE schemaname = 'public'"
FORCED="SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND c.relrowsecurity AND c.relforcerowsecurity"
MIGRATION="SELECT version_num FROM alembic_version"
APPEND_ONLY="SELECT count(*) FROM information_schema.table_privileges
             WHERE grantee = 'graphrec_app'
               AND table_name IN ('usage_events', 'audit_logs')
               AND privilege_type IN ('UPDATE', 'DELETE')"

for check in "tables:${TABLES}" "indexes:${INDEXES}" "policies:${POLICIES}" \
             "RLS enabled and forced:${FORCED}" "migration head:${MIGRATION}"; do
  compare "${check%%:*}" \
    "$(ask "$BACKUP_URL" "${check#*:}")" \
    "$(ask "$(backup_url_for "$SCRATCH")" "${check#*:}")"
done

# Not a comparison: this must be zero on the restored database whatever the
# live one says. An append-only table that came back writable is a restored
# database in which the audit log can be edited.
restored_writes="$(ask "$(backup_url_for "$SCRATCH")" "$APPEND_ONLY")"
if [ "$restored_writes" = "0" ]; then
  printf '    %-28s %-10s    %-10s ok\n' "append-only grants" "0" ""
else
  printf '    %-28s %-10s    %-10s FAILED\n' "append-only grants" "$restored_writes" ""
  FAILED=1
fi
echo

FINISHED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ "$FAILED" -eq 0 ]; then
  echo "=== drill PASSED  (${STARTED} → ${FINISHED})"
  echo "    backup:   ${BACKUP_DIR}"
  echo "    verified: rows, schema, policies, append-only grants"
  echo "    NOT verified: that an off-site copy exists. A script running on the"
  echo "                  machine being backed up cannot check that one."
else
  echo "=== drill FAILED  (${STARTED} → ${FINISHED})" >&2
  exit 1
fi

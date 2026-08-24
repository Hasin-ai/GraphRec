# shellcheck shell=bash
#
# Shared connection handling for the backup and restore scripts.
#
# Sourced, not executed. It exists because "where is the database" has three
# plausible answers on this project and the scripts must not each pick one:
#
#   * a local server, which is what a developer machine runs and what the test
#     suite talks to;
#   * a container in the Compose stack, which is what `docker-compose.yml`
#     starts;
#   * a managed instance on a private address, which is the deployment.
#
# All three are one libpq connection string, so that is what these scripts take.
# `GRAPHREC_OWNER_DATABASE_URL` is reused rather than a new variable because it
# is already what CI, Alembic and `tests/conftest.py` read, and a second name
# for the same thing is a second thing to get out of step.
#
# The SQLAlchemy prefix is stripped: `postgresql+psycopg://` is a SQLAlchemy
# dialect URL and libpq does not understand the driver half.

OWNER_URL="${GRAPHREC_OWNER_DATABASE_URL:-postgresql://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec}"
PGURL="${OWNER_URL/+psycopg/}"

# The database the URL names, and the same URL pointed at `postgres` instead —
# needed for CREATE/DROP DATABASE, which cannot run inside the database being
# created or dropped.
LIVE_DB="$(printf '%s' "$PGURL" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')"
# shellcheck disable=SC2034  # read by restore.sh, which sources this file
ADMIN_URL="$(printf '%s' "$PGURL" | sed -E "s#/${LIVE_DB}(\\?|\$)#/postgres\\1#")"

url_for() {
  # The same connection string aimed at a different database.
  printf '%s' "$PGURL" | sed -E "s#/${LIVE_DB}(\\?|\$)#/$1\\1#"
}

require_client() {
  for tool in psql pg_dump pg_restore pg_dumpall; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "missing ${tool}. Install the PostgreSQL client tools, or run these" >&2
      echo "scripts inside a container that has them." >&2
      exit 4
    fi
  done
}

# The role that takes and restores the dump, which is *not* `graphrec_owner`.
#
# This is the finding that Phase 16's first drill produced, and it is worth
# stating plainly because it is not obvious and it fails at exactly the wrong
# moment:
#
#     pg_dump: error: query failed: ERROR: query would be affected by
#     row-level security policy for table "api_keys"
#
# Every tenant table is `FORCE ROW LEVEL SECURITY`, which by design subjects the
# owner to the policies too (`migrations/0002`). `pg_dump` runs with
# `row_security = off`, which means "error rather than silently filter" — so as
# `graphrec_owner` the backup does not quietly come out empty, it refuses. That
# is the good outcome. The bad outcome is `pg_dump --enable-row-security`, which
# succeeds and writes a dump containing no tenant rows at all.
#
# So backups need a role that bypasses RLS: `postgres` on a self-hosted node,
# the admin role on a managed instance. That role is *not* an application
# credential, it is not in any service's environment, and it lives only where
# the backup job runs. Weakening FORCE to make the owner able to dump would
# trade the platform's isolation guarantee for a convenience.
BACKUP_URL="${GRAPHREC_SUPERUSER_DATABASE_URL:-$PGURL}"

require_rls_bypass() {
  # Refuse early and explain, rather than fail mid-dump with a message about
  # api_keys that reads like a permissions bug.
  local ok
  ok="$(psql "$BACKUP_URL" --no-align --tuples-only --quiet \
    -c "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user;" \
    2>/dev/null | tr -d '[:space:]')"
  if [ "$ok" = "t" ]; then
    return 0
  fi
  cat >&2 <<'MSG'
This connection cannot bypass row-level security, so it cannot back up or
restore this database.

Every tenant table is FORCE ROW LEVEL SECURITY, which applies to the table
owner as well. pg_dump runs with row_security = off and will error on the first
tenant table rather than write a dump with no rows in it.

Set GRAPHREC_SUPERUSER_DATABASE_URL to a role with BYPASSRLS or SUPERUSER —
`postgres` on a self-hosted node, the admin role on a managed instance. That
credential belongs to the backup job and to nothing else.

Do not "fix" this with ALTER TABLE NO FORCE ROW LEVEL SECURITY. FORCE is the
half of RLS that stops the migration role from reading across tenants.
MSG
  return 1
}

backup_url_for() {
  # `url_for`, but on the backup connection: the same admin role aimed at a
  # different database. Written against the last path segment rather than
  # against ${LIVE_DB} because the admin URL is supplied by whoever runs the
  # job and need not name the same database.
  printf '%s' "$BACKUP_URL" | sed -E "s#/[^/?]+(\\?|\$)#/$1\\1#"
}

# shellcheck disable=SC2034  # read by backup.sh and restore.sh
BACKUP_ADMIN_URL="$(printf '%s' "$BACKUP_URL" | sed -E 's#/[^/?]+(\?|$)#/postgres\1#')"

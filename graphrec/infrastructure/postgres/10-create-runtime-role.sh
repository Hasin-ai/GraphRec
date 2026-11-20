#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_password="$GRAPHREC_APP_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE graphrec_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'graphrec_app')
\gexec
ALTER ROLE graphrec_app NOBYPASSRLS;
SELECT format('GRANT CONNECT ON DATABASE %I TO graphrec_app', current_database())
\gexec
SQL

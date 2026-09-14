#!/bin/bash
# db-init service: run once against the Supabase Postgres of the Docker stack.
#   1. apply setup/db/schema/*.sql in order (reuses setup/db/apply_schema.sh) — skipped
#      when the schema is already present, so restarts are free
#   2. create/refresh the read-only role Grafana connects with
# Inputs: DATABASE_URL (postgres superuser), GRAFANA_DB_PASSWORD.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${GRAFANA_DB_PASSWORD:?GRAFANA_DB_PASSWORD is required}"

echo "⏳ waiting for postgres..."
for i in $(seq 1 60); do
    if psql "$DATABASE_URL" -tAc 'select 1' >/dev/null 2>&1; then break; fi
    sleep 2
    if [ "$i" -eq 60 ]; then echo "❌ postgres not reachable"; exit 1; fi
done

present="$(psql "$DATABASE_URL" -tAc "select 1 from information_schema.tables where table_schema='public' and table_name='device_models'")"
if [ "$present" = "1" ]; then
    echo "✅ schema already present — skipping setup/db/schema"
else
    echo "📦 applying setup/db/schema (fresh database)"
    DATABASE_URL="$DATABASE_URL" bash /setup-db/apply_schema.sh
fi

echo "👤 grafana_reader role"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader') THEN
        CREATE ROLE grafana_reader LOGIN;
    END IF;
END
\$\$;
ALTER ROLE grafana_reader WITH PASSWORD '${GRAFANA_DB_PASSWORD}';
GRANT USAGE ON SCHEMA public TO grafana_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_reader;
SQL
echo "🎉 db-init done"

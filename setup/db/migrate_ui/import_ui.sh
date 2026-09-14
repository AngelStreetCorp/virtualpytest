#!/bin/bash
# Import the example_tv UI definition CSVs (from export_ui.sh) into a destination Postgres.
# Keeps the same UUIDs and team_id. Leaves relative r2_url as-is (only absolute http(s)
# URLs are rewritten, and only when PROD_MINIO_PUBLIC_URL is given).
#
# Connection — pick ONE:
#   A) ENV_FILE — read SUPABASE_DB_URI from a deployment .env (simplest on a target VM):
#        ENV_FILE=/opt/virtualpytest/.env OUTDIR=./out ./import_ui.sh
#   B) PG_URI — a direct connection string:
#        PG_URI='postgresql://user:pass@host:5432/postgres' OUTDIR=./out ./import_ui.sh
#   C) discrete vars:
#        DST_HOST=host DST_PORT=5432 DST_USER=supabase_admin PGPASSWORD=*** OUTDIR=./out ./import_ui.sh
#
# Optional (only used to rewrite the rare ABSOLUTE r2_url rows):
#        PROD_MINIO_PUBLIC_URL=https://minio.prod PROD_BUCKET=virtualpytest
set -euo pipefail

OUTDIR="${OUTDIR:-./out}"

# Deployment .env can live in different places per VM (e.g. /opt/virtualpytest on synced
# hosts, /shared/code/virtualpytest on the storage VM) AND different files may carry
# different keys. Pick the first readable candidate that actually has the key we need.
# Override the search list with ENV_CANDIDATES (space-separated).
ENV_CANDIDATES="${ENV_CANDIDATES:-/opt/virtualpytest/.env /shared/code/virtualpytest/.env ./.env}"
env_val() { grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'\r'; }
pick_env_with() {  # $1 = key that must be non-empty; echoes the chosen file
  for f in $ENV_CANDIDATES; do
    [ -r "$f" ] || continue
    [ -n "$(env_val "$f" "$1")" ] && { echo "$f"; return 0; }
  done
  return 1
}

# Resolve a Postgres connection. Explicit PG_URI / DST_HOST win; otherwise read an .env.
if [ -z "${PG_URI:-}" ] && [ -z "${DST_HOST:-}" ]; then
  ENV_FILE="${ENV_FILE:-$(pick_env_with SUPABASE_DB_URI || true)}"
  [ -n "${ENV_FILE:-}" ] || { echo "ERROR: no .env with SUPABASE_DB_URI found ($ENV_CANDIDATES); set ENV_FILE / PG_URI / DST_HOST" >&2; exit 1; }
  [ -r "$ENV_FILE" ] || { echo "ERROR: ENV_FILE not readable: $ENV_FILE" >&2; exit 1; }
  echo "Using ENV_FILE for DB: $ENV_FILE"
  PG_URI="$(env_val "$ENV_FILE" SUPABASE_DB_URI)"
  [ -n "$PG_URI" ] || { echo "ERROR: no SUPABASE_DB_URI in $ENV_FILE" >&2; exit 1; }
fi
if [ -n "${PG_URI:-}" ]; then
  PSQL="psql $PG_URI -v ON_ERROR_STOP=1"
else
  DST_HOST="${DST_HOST:?set ENV_FILE, PG_URI, or DST_HOST}"
  DST_PORT="${DST_PORT:-5432}"; DST_DB="${DST_DB:-postgres}"; DST_USER="${DST_USER:-supabase_admin}"
  export PGPASSWORD="${PGPASSWORD:?set PGPASSWORD (or use ENV_FILE / PG_URI)}"
  PSQL="psql -h $DST_HOST -p $DST_PORT -d $DST_DB -U $DST_USER -v ON_ERROR_STOP=1"
fi

PROD_BUCKET="${PROD_BUCKET:-virtualpytest}"

# shellcheck disable=SC1090
source "$OUTDIR/manifest.env"
BASE="${PROD_MINIO_PUBLIC_URL:-}"; BASE="${BASE%/}${BASE:+/$PROD_BUCKET}"

# Preflight: the teams row must exist (same team_id, FK target).
HAS_TEAM=$($PSQL -tAc "SELECT 1 FROM teams WHERE id = '$TEAM_ID';" || true)
if [ "$HAS_TEAM" != "1" ]; then
  echo "ERROR: team_id $TEAM_ID does not exist on prod. Seed the teams row first." >&2
  exit 1
fi

copy_in() {
  local table="$1"
  local cols; cols=$(cat "$OUTDIR/$table.cols")
  echo "  $table"
  # ON CONFLICT-free: rely on delete-then-load below for idempotency.
  $PSQL -c "\copy $table ($cols) FROM '$OUTDIR/$table.csv' WITH (FORMAT csv, HEADER true)"
}

$PSQL <<SQL
BEGIN;
SET session_replication_role = replica;  -- defer FK checks + triggers + check constraints

-- Idempotent re-run: remove any prior copy of this UI's definition (same UUIDs).
DELETE FROM userinterface_variants   WHERE userinterface_id = '$UI_ID';
DELETE FROM verifications_references  WHERE userinterface_name = '$UI_NAME' OR userinterface_id = '$UI_ID';
DELETE FROM navigation_edges WHERE tree_id IN (SELECT id FROM navigation_trees WHERE userinterface_id = '$UI_ID');
DELETE FROM navigation_nodes WHERE tree_id IN (SELECT id FROM navigation_trees WHERE userinterface_id = '$UI_ID');
DELETE FROM navigation_trees WHERE userinterface_id = '$UI_ID';
DELETE FROM userinterfaces   WHERE id = '$UI_ID';
COMMIT;
SQL

# Load in FK order (session_replication_role only applies per-session, so do the COPYs
# inside one psql session that also keeps replica mode on).
# All COPYs run in ONE transaction so a mid-load failure rolls back everything
# (no partial state where nodes load but edges don't). \set ON_ERROR_STOP + the
# single BEGIN/COMMIT make it all-or-nothing.
$PSQL <<SQL
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL session_replication_role = replica;
\copy userinterfaces ($(cat "$OUTDIR/userinterfaces.cols")) FROM '$OUTDIR/userinterfaces.csv' WITH (FORMAT csv, HEADER true)
\copy navigation_trees ($(cat "$OUTDIR/navigation_trees.cols")) FROM '$OUTDIR/navigation_trees.csv' WITH (FORMAT csv, HEADER true)
\copy navigation_nodes ($(cat "$OUTDIR/navigation_nodes.cols")) FROM '$OUTDIR/navigation_nodes.csv' WITH (FORMAT csv, HEADER true)
\copy navigation_edges ($(cat "$OUTDIR/navigation_edges.cols")) FROM '$OUTDIR/navigation_edges.csv' WITH (FORMAT csv, HEADER true)
\copy userinterface_variants ($(cat "$OUTDIR/userinterface_variants.cols")) FROM '$OUTDIR/userinterface_variants.csv' WITH (FORMAT csv, HEADER true)
\copy verifications_references ($(cat "$OUTDIR/verifications_references.cols")) FROM '$OUTDIR/verifications_references.csv' WITH (FORMAT csv, HEADER true)

${BASE:+-- Reference URLs: relative r2_url (== r2_path) is endpoint-independent and left as-is.}
${BASE:+-- Only absolute http(s) rows are rewritten to the prod endpoint/bucket (r2_path unchanged).}
${BASE:+UPDATE verifications_references SET r2_url = '$BASE/' || ltrim(r2_path, '/') WHERE (userinterface_name = '$UI_NAME' OR userinterface_id = '$UI_ID') AND r2_url ~ '^https?://';}
COMMIT;
SQL

# Triggers were disabled during the load (replica mode), so the materialized view the
# triggers normally maintain is stale — refresh it. Then reload PostgREST's schema cache
# (the import wrote straight to Postgres, bypassing PostgREST, so its cache is stale —
# this is what made edges invisible while nodes still rendered).
$PSQL <<SQL || true
REFRESH MATERIALIZED VIEW public.mv_full_navigation_trees;
SQL
$PSQL -c "NOTIFY pgrst, 'reload schema';" || true

echo "Import complete. Verify counts below:"
$PSQL -c "
SELECT 'trees' t, count(*) FROM navigation_trees WHERE userinterface_id='$UI_ID'
UNION ALL SELECT 'nodes', count(*) FROM navigation_nodes WHERE tree_id IN (SELECT id FROM navigation_trees WHERE userinterface_id='$UI_ID')
UNION ALL SELECT 'edges', count(*) FROM navigation_edges WHERE tree_id IN (SELECT id FROM navigation_trees WHERE userinterface_id='$UI_ID')
UNION ALL SELECT 'variants', count(*) FROM userinterface_variants WHERE userinterface_id='$UI_ID'
UNION ALL SELECT 'refs', count(*) FROM verifications_references WHERE userinterface_name='$UI_NAME' OR userinterface_id='$UI_ID';"
echo "Materialized view refreshed and PostgREST schema reloaded. If edges still don't render,"
echo "restart the backend (vpt-server) to clear its in-memory navigation cache, then hard-refresh."

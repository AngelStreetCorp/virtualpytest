#!/bin/bash
# VirtualPyTest - Apply database schema to a fresh Supabase/Postgres database
#
# Applies every setup/db/schema/*.sql file in filename order, one at a time,
# stopping on the first error. For migrating an ALREADY-populated database,
# use setup/db/migrations/ instead (see docs/agent/infra/DATABASE.md) — this
# script is for a brand-new database only.
#
# Usage:
#   DATABASE_URL="postgresql://postgres:PASSWORD@db.PROJECT-REF.supabase.co:5432/postgres" \
#     ./setup/db/apply_schema.sh
#
#   ./setup/db/apply_schema.sh "postgresql://postgres:PASSWORD@db.PROJECT-REF.supabase.co:5432/postgres"
#
#   ./setup/db/apply_schema.sh --dry-run          # list files in order, apply nothing
#
# Requires: psql (the PostgreSQL client). On Supabase, get the connection
# string from Settings -> Database -> Connection string ("URI" tab).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_DIR="$SCRIPT_DIR/schema"

DRY_RUN=false
CONN=""
for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN=true
    else
        CONN="$arg"
    fi
done
CONN="${CONN:-${DATABASE_URL:-}}"

if [[ "$DRY_RUN" == false && -z "$CONN" ]]; then
    echo "❌ No database connection string given." >&2
    echo "   Pass it as an argument or set DATABASE_URL. See the header of this script." >&2
    exit 1
fi

if [[ "$DRY_RUN" == false ]] && ! command -v psql &> /dev/null; then
    echo "❌ psql not found. Install the PostgreSQL client and try again." >&2
    exit 1
fi

if [[ ! -d "$SCHEMA_DIR" ]]; then
    echo "❌ Schema directory not found: $SCHEMA_DIR" >&2
    exit 1
fi

FILE_LIST="$(find "$SCHEMA_DIR" -maxdepth 1 -name '*.sql' -print | sort)"
TOTAL="$(echo "$FILE_LIST" | grep -c . || true)"

if [[ "$TOTAL" -eq 0 ]]; then
    echo "❌ No .sql files found in $SCHEMA_DIR" >&2
    exit 1
fi

echo "📦 $TOTAL schema files found in $SCHEMA_DIR"
echo ""

if [[ "$DRY_RUN" == true ]]; then
    echo "Dry run — files that would be applied, in order:"
    echo "$FILE_LIST" | while IFS= read -r f; do
        echo "  $(basename "$f")"
    done
    echo "  migrations/20260908b_close_app_tables_to_public_key.sql   (lockdown, applied last)"
    exit 0
fi

COUNT=0
while IFS= read -r f; do
    COUNT=$((COUNT + 1))
    name="$(basename "$f")"
    echo "[$COUNT/$TOTAL] Applying $name ..."
    if ! psql "$CONN" -v ON_ERROR_STOP=1 -q -f "$f"; then
        echo ""
        echo "❌ Failed on $name (file $COUNT of $TOTAL)."
        echo "   Fix the error above, then re-run this script — files before this one already"
        echo "   applied. If a table/type already exists from a partial run, drop it manually"
        echo "   or restore from a fresh database before retrying."
        exit 1
    fi
done <<< "$FILE_LIST"

echo ""
echo "✅ Applied all $TOTAL schema files successfully."

# The schema files still carry the historical open policies (USING (true) for every
# role). Production closed the app tables to the anon key in September 2026 (TASK-10);
# a fresh database gets the same posture by applying that idempotent migration last.
LOCKDOWN="$SCRIPT_DIR/migrations/20260908b_close_app_tables_to_public_key.sql"
if [[ -f "$LOCKDOWN" ]]; then
    echo "🔒 Closing app tables to the anon key ($(basename "$LOCKDOWN")) ..."
    if ! psql "$CONN" -v ON_ERROR_STOP=1 -q -f "$LOCKDOWN"; then
        echo "❌ Lockdown migration failed — the database is usable but the anon key can read app tables."
        exit 1
    fi
    echo "✅ App tables closed to anon; server and hosts must use SUPABASE_SERVICE_ROLE_KEY."
fi

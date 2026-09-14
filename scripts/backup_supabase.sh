#!/bin/bash

set -e

# Use PostgreSQL 17 if available
if [ -d "/opt/homebrew/opt/postgresql@17/bin" ]; then
    export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/setup/db/backup"
ENV_FILE="$PROJECT_ROOT/.env"

# Load .env
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ .env file not found at $ENV_FILE"
    exit 1
fi

set -a
set +e; source "$ENV_FILE" 2>/dev/null; set -e
set +a

# Use SUPABASE_DB_URI if available, otherwise build from separate variables
if [ -n "$SUPABASE_DB_URI" ]; then
    DB_URL="$SUPABASE_DB_URI"
elif [ -n "$DATABASE_URL" ]; then
    DB_URL="$DATABASE_URL"
elif [ -n "$DB_HOST" ] && [ -n "$DB_NAME" ] && [ -n "$DB_USER" ] && [ -n "$DB_PASSWORD" ]; then
    [ -z "$DB_PORT" ] && DB_PORT=5432
    DB_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
else
    echo "❌ Missing DB credentials in .env"
    echo "   Required: SUPABASE_DB_URI or DATABASE_URL or (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD)"
    exit 1
fi

if ! command -v pg_dump >/dev/null 2>&1; then
    echo "❌ pg_dump not found"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/supabase_backup_$TIMESTAMP.sql"

echo "Creating backup..."

# Use --no-sync for compatibility and ignore version mismatch warnings
export PGPASSWORD
if pg_dump "$DB_URL" --no-sync > "$BACKUP_FILE" 2>&1; then
    gzip "$BACKUP_FILE"
    FILENAME="$(basename "$BACKUP_FILE").gz"
    SIZE=$(du -sh "${BACKUP_FILE}.gz" | cut -f1)
    echo "✅ Backup created: ${BACKUP_FILE}.gz (${SIZE})"

    # Report status to backend server so the Status page reflects this backup
    BACKEND_URL="${SERVER_URL:-http://localhost:5109}"
    TIMESTAMP_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    curl -s -X POST "${BACKEND_URL}/server/system/backup/report" \
      -H "Content-Type: application/json" \
      -d "{\"filename\":\"${FILENAME}\",\"size\":\"${SIZE}\",\"timestamp_iso\":\"${TIMESTAMP_ISO}\",\"nfs_copy\":false}" \
      && echo "✅ Backup status reported to ${BACKEND_URL}" \
      || echo "⚠️  Could not report backup status (server unreachable — non-fatal)"
else
    cat "$BACKUP_FILE"
    echo "❌ Backup failed - see error above"
    rm -f "$BACKUP_FILE"
    exit 1
fi


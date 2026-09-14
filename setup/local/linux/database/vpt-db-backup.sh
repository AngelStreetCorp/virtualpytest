#!/bin/bash
# vpt-db-backup.sh
# Daily PostgreSQL backup for VirtualPyTest database VM.
# Installed to /usr/local/bin/vpt-db-backup.sh by install_supabase.sh
#
# Saves a pg_dump to local /data/backups/ and NFS /mnt/shared/database/backup/
# After each backup, POSTs status to the backend server so the Status page
# can show last backup time and alert if a backup is missed.
#
# Retention:
#   Local  (/data/backups/)              — 7 days
#   Remote (/mnt/shared/database/backup) — 30 days
#
# Run via cron (see /etc/cron.d/vpt-db-backup) or manually:
#   sudo bash /usr/local/bin/vpt-db-backup.sh

set -euo pipefail

CONTAINER="supabase_db_supabase"
DB_USER="postgres"
DB_NAME="postgres"
LOCAL_DIR="/data/backups"
NFS_DIR="/mnt/shared/database/backup"
BACKEND_URL="${VPT_BACKEND_URL:-http://localhost:5109}"
# Shared service key (backend .env API_KEY). /server/* is closed by default,
# so the status POST is rejected with 401 without it. Set VPT_API_KEY in
# /etc/cron.d/vpt-db-backup (the installer does this) or in the environment.
API_KEY="${VPT_API_KEY:-}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="vpt_postgres_${TIMESTAMP}.dump"

mkdir -p "$LOCAL_DIR"

echo "[$(date)] Starting backup: $FILENAME"

# Dump all schemas (public + supabase internals) in custom format
docker exec "$CONTAINER" pg_dump \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  -F c \
  -f "/tmp/${FILENAME}"

# Copy from container to local disk
docker cp "${CONTAINER}:/tmp/${FILENAME}" "${LOCAL_DIR}/${FILENAME}"

# Cleanup temp file in container
docker exec "$CONTAINER" rm -f "/tmp/${FILENAME}"

SIZE=$(du -sh "${LOCAL_DIR}/${FILENAME}" | cut -f1)
echo "[$(date)] Saved locally: ${LOCAL_DIR}/${FILENAME} (${SIZE})"

# Copy to NFS if mounted
NFS_OK=false
if mountpoint -q "$NFS_DIR"; then
  cp "${LOCAL_DIR}/${FILENAME}" "${NFS_DIR}/${FILENAME}"
  NFS_OK=true
  echo "[$(date)] Copied to NFS: ${NFS_DIR}/${FILENAME}"
else
  echo "[$(date)] INFO: NFS not mounted at $NFS_DIR — local backup only"
fi

# Prune local: keep 7 days
find "$LOCAL_DIR" -name "vpt_postgres_*.dump" -mtime +7 -delete
echo "[$(date)] Pruned local backups older than 7 days"

# Prune NFS: keep 30 days
if $NFS_OK; then
  find "$NFS_DIR" -name "vpt_postgres_*.dump" -mtime +30 -delete
  echo "[$(date)] Pruned NFS backups older than 30 days"
fi

# Report status to backend server (non-fatal if server is unreachable)
TIMESTAMP_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
curl -s -f -X POST "${BACKEND_URL}/server/system/backup/report" \
  -H "Content-Type: application/json" \
  ${API_KEY:+-H "X-API-Key: ${API_KEY}"} \
  -d "{\"filename\":\"${FILENAME}\",\"size\":\"${SIZE}\",\"timestamp_iso\":\"${TIMESTAMP_ISO}\",\"nfs_copy\":${NFS_OK}}" \
  && echo "[$(date)] Status reported to backend." \
  || echo "[$(date)] WARNING: Could not report status to backend (non-fatal)."

echo "[$(date)] Backup complete."

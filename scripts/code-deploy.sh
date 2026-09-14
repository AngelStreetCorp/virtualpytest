#!/bin/bash
# code-deploy.sh — sync code from shared storage to target dir with backup support
# Called by backend_host and backend_server deploy routes.
#
# Env vars (all required):
#   VPT_SOURCE_DIR    — source path (e.g. /mnt/shared/code/virtualpytest)
#   VPT_TARGET_DIR    — deploy target (e.g. /opt/virtualpytest)
#   VPT_BACKUP_ROOT   — where backups live (e.g. /var/tmp/virtualpytest_backups)
#   VPT_KEEP_BACKUPS  — how many backups to retain (default: 5)
#   VPT_DRY_RUN       — 1 = dry run (no changes), 0 = real run
#   VPT_TARGET_KIND   — server | frontend | host-linux (used for context only)
#   VPT_RESTART_ENABLED — 1 = restart service after sync, 0 = skip
#
# Stdout KV pairs consumed by the caller:
#   VERSION_BEFORE=<string>
#   VERSION_AFTER=<string>
#   BACKUP_DIR=<path>

set -euo pipefail

SOURCE_DIR="${VPT_SOURCE_DIR:-/mnt/shared/code/virtualpytest}"
TARGET_DIR="${VPT_TARGET_DIR:-/opt/virtualpytest}"
BACKUP_ROOT="${VPT_BACKUP_ROOT:-/var/tmp/virtualpytest_backups}"
KEEP_BACKUPS="${VPT_KEEP_BACKUPS:-5}"
DRY_RUN="${VPT_DRY_RUN:-0}"
TARGET_KIND="${VPT_TARGET_KIND:-host-linux}"
RESTART_ENABLED="${VPT_RESTART_ENABLED:-0}"

# Read version from VERSION.txt or version file
read_version() {
    local dir="$1"
    local f
    for f in "$dir/VERSION.txt" "$dir/version"; do
        if [[ -f "$f" ]]; then
            head -1 "$f" | tr -d '[:space:]' && return
        fi
    done
    echo "unknown"
}

VERSION_BEFORE="$(read_version "$TARGET_DIR")"
echo "VERSION_BEFORE=${VERSION_BEFORE}"

BACKUP_DIR=""

if [[ "$DRY_RUN" == "1" ]]; then
    echo "--- DRY RUN: no changes will be made ---"
    rsync -av --dry-run --delete \
        --exclude='.git' \
        --exclude='.github' \
        --exclude='.cursor' \
        --exclude='.husky' \
        --exclude='.env' \
        --exclude='venv' \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='*.pyo' \
        --exclude='frontend/public/docs' \
        --exclude='frontend/dist' \
        --exclude='playwright-report*' \
        --exclude='playwright-viewport-report*' \
        --exclude='security_report' \
        --exclude='frontend/vite.config.local.json' \
        --exclude='frontend/public/branding.json' \
        --exclude='frontend/public/brand' \
        --exclude='frontend/public/favicon.ico' \
        --exclude='frontend/public/logo.png' \
        "${SOURCE_DIR}/" "${TARGET_DIR}/"
    echo "VERSION_AFTER=${VERSION_BEFORE}"
    echo "BACKUP_DIR="
    exit 0
fi

# Create backup
mkdir -p "${BACKUP_ROOT}"
TIMESTAMP="$(date -u +%Y%m%d_%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
mkdir -p "${BACKUP_DIR}"
rsync -a --delete \
    --exclude='.env' \
    --exclude='venv' \
    --exclude='node_modules' \
    --exclude='frontend/dist' \
    "${TARGET_DIR}/" "${BACKUP_DIR}/"
echo "BACKUP_DIR=${BACKUP_DIR}"

# Prune old backups (keep most recent N)
if [[ "${KEEP_BACKUPS}" =~ ^[0-9]+$ ]] && (( KEEP_BACKUPS > 0 )); then
    find "${BACKUP_ROOT}" -maxdepth 1 -mindepth 1 -type d | sort | head -n "-${KEEP_BACKUPS}" | xargs -r rm -rf
fi

# Sync source to target
cd /
rsync -av --delete \
    --exclude='.git' \
    --exclude='.github' \
    --exclude='.cursor' \
    --exclude='.husky' \
    --exclude='.env' \
    --exclude='venv' \
    --exclude='node_modules' \
    --exclude='frontend/public/docs' \
    --exclude='frontend/dist' \
    --exclude='playwright-report*' \
    --exclude='playwright-viewport-report*' \
    --exclude='security_report' \
    --exclude='frontend/vite.config.local.json' \
    --exclude='frontend/public/branding.json' \
    --exclude='frontend/public/brand' \
    --exclude='frontend/public/favicon.ico' \
    --exclude='frontend/public/logo.png' \
    "${SOURCE_DIR}/" "${TARGET_DIR}/"

# Fix ownership
find "${TARGET_DIR}" \
    -path "${TARGET_DIR}/frontend/public/docs" -prune -o \
    -path "${TARGET_DIR}/frontend/public/brand" -prune -o \
    -not -path '*/.env' -not -path '*/venv/*' -exec chown vpt_user:vpt_user {} + 2>/dev/null || true

VERSION_AFTER="$(read_version "$TARGET_DIR")"
echo "VERSION_AFTER=${VERSION_AFTER}"

echo "Code sync completed (${TARGET_KIND}): ${VERSION_BEFORE} -> ${VERSION_AFTER}"

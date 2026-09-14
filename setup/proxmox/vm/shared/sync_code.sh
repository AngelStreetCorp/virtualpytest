#!/bin/bash
set -e

# Usage: sync_code.sh [source_dir]
# Default source: /mnt/shared/code/virtualpytest/
SOURCE_DIR="${1:-/mnt/shared/code/virtualpytest}"
TARGET_DIR="/opt/virtualpytest"

cd /

# Sync code, excluding venv, .env, and node_modules directories
rsync -av --delete \
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
    --exclude='backend_host/config/user_data' \
    --exclude='backend_host/config/webkit_user_data' \
    --exclude='frontend/vite.config.local.json' \
    --exclude='frontend/public/branding.json' \
    --exclude='frontend/public/brand' \
    --exclude='frontend/public/favicon.ico' \
    --exclude='frontend/public/logo.png' \
    --exclude='test_scripts/script_identity_map.json' \
    --exclude='test_campaign/campaign_identity_map.json' \
    "${SOURCE_DIR}/" "${TARGET_DIR}/"

# Change ownership excluding generated frontend docs and env/venv managed paths.
# Some VM tasks may create root-owned generated docs; don't fail sync on those.
find "${TARGET_DIR}" \
    -path "${TARGET_DIR}/frontend/public/docs" -prune -o \
    -path "${TARGET_DIR}/frontend/public/brand" -prune -o \
    -not -path '*/.env' -not -path '*/venv/*' -exec chown vpt_user:vpt_user {} + 2>/dev/null || true

echo "Code sync completed. Runtime artifacts and repo metadata excluded from sync."

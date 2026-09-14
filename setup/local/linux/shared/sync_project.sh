#!/bin/bash

# VirtualPyTest - Sync project into /opt/virtualpytest
# Requires git repo and performs a mandatory git pull.

set -e

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
TARGET_ROOT="/opt/virtualpytest"

if [ "$SOURCE_ROOT" = "$TARGET_ROOT" ]; then
    echo "❌ Refusing to sync from /opt/virtualpytest."
    echo "   Run from a repo clone (e.g., /home/<user>/virtualpytest)."
    exit 1
fi

if [ ! -d "$SOURCE_ROOT/.git" ]; then
    echo "❌ Not a git repository. Git is required for sync."
    exit 1
fi

echo "🔄 Updating repo (git pull --ff-only)..."
git -C "$SOURCE_ROOT" pull --ff-only

echo "📦 Syncing project to $TARGET_ROOT..."
sudo mkdir -p "$TARGET_ROOT"
sudo rsync -a --delete \
  --exclude '.git' \
  --exclude '.env' \
  --exclude 'backend_host/src/.env' \
  --exclude 'frontend/.env' \
  --exclude 'backend_server/.env' \
  --exclude 'frontend/vite.config.local.json' \
  --exclude 'frontend/public/branding.json' \
  --exclude 'node_modules' \
  --exclude 'venv' \
  "$SOURCE_ROOT/" "$TARGET_ROOT/"

sudo chown -R vpt_user:vpt_user "$TARGET_ROOT"
echo "✅ Sync complete: $TARGET_ROOT"

#!/bin/bash
# patch_add_backup_cron.sh
#
# One-shot patch for existing database VMs that don't have the backup cron yet.
# Safe to run on a live system — does not touch Supabase containers or data.
#
# Usage (run as root or with sudo):
#   sudo bash patch_add_backup_cron.sh
#
# Or from the project root on the database VM:
#   ssh database "echo $SUDO_PASSWORD | sudo -S bash /opt/virtualpytest/setup/local/linux/database/patch_add_backup_cron.sh"

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT_SRC="${SCRIPT_DIR}/vpt-db-backup.sh"
BACKUP_SCRIPT_DST="/usr/local/bin/vpt-db-backup.sh"
CRON_FILE="/etc/cron.d/vpt-db-backup"

echo "=== VirtualPyTest Backup Cron Patch ==="

# Check already installed
if [ -f "$CRON_FILE" ] && [ -f "$BACKUP_SCRIPT_DST" ]; then
    echo "✅ Backup cron already installed — nothing to do."
    echo "   Cron:   $CRON_FILE"
    echo "   Script: $BACKUP_SCRIPT_DST"
    exit 0
fi

if [ ! -f "$BACKUP_SCRIPT_SRC" ]; then
    echo "❌ Source script not found: $BACKUP_SCRIPT_SRC"
    echo "   Run this from the repo or pull latest code first."
    exit 1
fi

# Backend URL: VPT_BACKEND_URL if given, else SERVER_URL from the installed .env, else this machine
BACKEND_URL="${VPT_BACKEND_URL:-$(grep -E '^SERVER_URL=' /opt/virtualpytest/.env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"')}"
BACKEND_URL="${BACKEND_URL:-http://localhost:5109}"
echo "Backend URL: $BACKEND_URL"

# Install backup script
sed "s|VPT_BACKEND_URL:-http://localhost:5109|VPT_BACKEND_URL:-${BACKEND_URL}|" \
    "$BACKUP_SCRIPT_SRC" > "$BACKUP_SCRIPT_DST"
chmod +x "$BACKUP_SCRIPT_DST"
echo "✅ Installed: $BACKUP_SCRIPT_DST"

# Create backup directory
mkdir -p /data/backups
echo "✅ Directory: /data/backups"

# Shared service key so the status POST passes the server's /server/* guard
# (closed by default). Pass VPT_API_KEY=<backend API_KEY> when running this patch.
VPT_API_KEY="${VPT_API_KEY:-}"
if [ -z "$VPT_API_KEY" ]; then
    echo "⚠️  VPT_API_KEY not set — status reports will be rejected (401) until you add VPT_API_KEY=<backend API_KEY> to $CRON_FILE"
fi

# Install cron. File holds the service key: root-only.
cat > "$CRON_FILE" << EOF
# VirtualPyTest daily PostgreSQL backup — runs at 02:00
# Logs to /var/log/vpt-db-backup.log
VPT_API_KEY=${VPT_API_KEY}
0 2 * * * root /usr/local/bin/vpt-db-backup.sh >> /var/log/vpt-db-backup.log 2>&1
EOF
chmod 600 "$CRON_FILE"
echo "✅ Cron installed: $CRON_FILE"

# Run once now to seed the status
echo ""
echo "Running first backup now to seed status..."
bash "$BACKUP_SCRIPT_DST" && echo "✅ First backup complete." || echo "⚠️  First backup failed — check logs."

echo ""
echo "=== Patch complete ==="
echo "   Daily backups will run at 02:00."
echo "   Log: /var/log/vpt-db-backup.log"
echo "   Run manually: sudo bash $BACKUP_SCRIPT_DST"

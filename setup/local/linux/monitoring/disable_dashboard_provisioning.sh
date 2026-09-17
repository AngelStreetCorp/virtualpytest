#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

PROVISIONING_DIR="/etc/grafana/provisioning/dashboards"
BACKUP_DIR="/etc/grafana/provisioning/dashboards.backup.$(date +%Y%m%d_%H%M%S)"

echo "🛠️  Disabling Grafana dashboard file provisioning..."

if ! command -v systemctl >/dev/null 2>&1; then
    echo "❌ systemctl not found"
    exit 1
fi

sudo mkdir -p "$PROVISIONING_DIR"

if compgen -G "$PROVISIONING_DIR/*" >/dev/null; then
    echo "📦 Backing up existing dashboard provisioning files to $BACKUP_DIR"
    sudo mkdir -p "$BACKUP_DIR"
    sudo cp -a "$PROVISIONING_DIR"/. "$BACKUP_DIR"/
fi

echo "🧹 Removing existing dashboard provisioning files..."
sudo rm -f "$PROVISIONING_DIR"/*.yaml "$PROVISIONING_DIR"/*.yml

echo "📄 Writing empty dashboard provider config..."
sudo tee "$PROVISIONING_DIR/default.yaml" > /dev/null <<'EOF'
apiVersion: 1

providers: []
EOF

if [ -f /var/lib/grafana/grafana.db ]; then
    DB_BACKUP="/var/lib/grafana/grafana.db.backup.$(date +%Y%m%d_%H%M%S)"
    echo "💾 Backing up Grafana database to $DB_BACKUP"
    sudo cp /var/lib/grafana/grafana.db "$DB_BACKUP"

    echo "🧹 Clearing stale dashboard provisioning rows from Grafana database..."
    sudo python3 - <<'PY'
import sqlite3

conn = sqlite3.connect("/var/lib/grafana/grafana.db")
cur = conn.cursor()
cur.execute("DELETE FROM dashboard_provisioning")
conn.commit()
conn.close()
PY
fi

echo "🔄 Restarting grafana-server..."
sudo systemctl restart grafana-server

echo "✅ Dashboard file provisioning disabled"
echo "   Backup: $BACKUP_DIR"
echo "   Verify: curl -su admin:\"\$GRAFANA_ADMIN_PASSWORD\" http://127.0.0.1:3000/grafana/api/search?type=dash-db"

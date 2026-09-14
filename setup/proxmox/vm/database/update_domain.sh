#!/bin/bash
# update_domain.sh
#
# Updates the production domain across all config files that hardcode it.
# Run this on the DATABASE VM when changing the domain.
#
# Usage:
#   sudo bash update_domain.sh virtualpytest.com
#
# What this updates:
#   - /data/supabase/supabase/config.toml  (site_url, redirect_urls, OAuth redirect_uri)
#
# What you must update MANUALLY after running this script:
#   - GitHub OAuth app callback URL  → https://github.com/settings/developers
#   - Google OAuth app redirect URI  → https://console.cloud.google.com
#   - DNS: point new domain to <origin-ip>
#   - SSL cert: regenerate for the new domain

set -e

NEW_DOMAIN="${1:-}"
if [ -z "$NEW_DOMAIN" ]; then
  echo "Usage: sudo bash update_domain.sh <new-domain>"
  echo "Example: sudo bash update_domain.sh virtualpytest.com"
  exit 1
fi

CONFIG="/data/supabase/supabase/config.toml"
BACKUP_DIR="/etc/supabase_backups"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: $CONFIG not found. Run this on the database VM."
  exit 1
fi

# Detect current domain
CURRENT_DOMAIN=$(grep 'site_url' "$CONFIG" | grep -oP 'https?://\K[^"]+')
if [ -z "$CURRENT_DOMAIN" ]; then
  echo "ERROR: Could not detect current domain from $CONFIG"
  exit 1
fi

echo "Current domain: $CURRENT_DOMAIN"
echo "New domain:     $NEW_DOMAIN"
echo ""

# Backup
mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/config.toml.bak.$(date +%Y%m%d_%H%M%S)"
cp "$CONFIG" "$BACKUP"
echo "Backup saved to $BACKUP"

# Replace all occurrences of the old domain in config.toml
python3 - "$CONFIG" "$CURRENT_DOMAIN" "$NEW_DOMAIN" << 'EOF'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, 'r') as f:
    content = f.read()
updated = content.replace(old, new)
count = content.count(old)
with open(path, 'w') as f:
    f.write(updated)
print(f"Replaced {count} occurrence(s) of '{old}' with '{new}'")
EOF

echo ""
echo "Restarting Supabase to apply config changes..."
# supabase stop/start is required — containers read env vars baked in at startup,
# not live from config.toml. docker restart alone is NOT enough for config changes.
# Data is safe: supabase stop preserves named Docker volumes (supabase_db_supabase).
cd /data/supabase/supabase
supabase stop
supabase start

echo ""
echo "Done. Domain updated from $CURRENT_DOMAIN to $NEW_DOMAIN"
echo ""
echo "Don't forget to update manually:"
echo "  1. GitHub OAuth callback URL: https://github.com/settings/developers"
echo "  2. Google OAuth redirect URI: https://console.cloud.google.com"
echo "  3. DNS: point $NEW_DOMAIN to <origin-ip>"
echo "  4. SSL cert: regenerate for $NEW_DOMAIN"

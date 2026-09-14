#!/usr/bin/env bash
# Fast single-file deploy to host1 — skip the full git/commit/pull/rsync cycle.
# Use during iterative testing when you're editing one backend_server file over
# and over and don't want to go through update_core.sh each time.
#
# Usage:
#   scripts/quickdeploy.sh backend_server/src/mcp/tools/screenshot_tools.py
#   scripts/quickdeploy.sh backend_server/src/mcp/tools/screenshot_tools.py --restart
#   scripts/quickdeploy.sh --pack /tmp/atlas_pack_test.txt  # prompt file to host1:/tmp
#
# Flags:
#   --restart   Restart vpt-server after rsync (default: no restart, just rsync)
#   --pack      Treat the path as a prompt file destined for host1:/tmp/atlas_pack_test.txt
#               (no service restart needed — this file is read by atlas_chat on each run)
#
# NOTE: committed files end up on host1 at /opt/virtualpytest/<same-relative-path>.
# The commit/push/merge/update_core.sh path is still the correct one for final
# delivery — this is ONLY for fast iteration.

set -eu

RESTART=false
PACK=false
FILE=""
for arg in "$@"; do
  case "$arg" in
    --restart) RESTART=true ;;
    --pack)    PACK=true ;;
    *)         FILE="$arg" ;;
  esac
done

if [[ -z "$FILE" ]]; then
  echo "usage: scripts/quickdeploy.sh <path> [--restart] [--pack]" >&2
  exit 1
fi
if [[ ! -f "$FILE" ]]; then
  echo "error: file not found: $FILE" >&2
  exit 1
fi

if $PACK; then
  # Prompt / pack files go to /tmp on host1 — no service restart needed
  dest="/tmp/$(basename "$FILE")"
  echo "→ copying $FILE to host1:$dest"
  scp -o ProxyJump=proxmox -q "$FILE" "host1:$dest"
  ssh proxmox "ssh host1 'wc -l $dest'"
  exit 0
fi

# Code path: push to /opt/virtualpytest/<relative>
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
rel="${FILE#${repo_root}/}"
dest="/opt/virtualpytest/$rel"

echo "→ copying $FILE to host1:$dest"
# Stage via proxmox since host1 isn't directly reachable
scp -o ProxyJump=proxmox -q "$FILE" "host1:/tmp/_qd_$(basename "$FILE")"
# Move into place (needs vpt_user ownership under /opt/virtualpytest)
ssh proxmox "ssh host1 'sudo -n install -o vpt_user -g vpt_user -m 644 /tmp/_qd_$(basename "$FILE") $dest && rm /tmp/_qd_$(basename "$FILE")'"

echo "✓ synced"

if $RESTART; then
  echo "→ restarting vpt-server..."
  ssh proxmox "ssh host1 'sudo -n systemctl restart vpt-server.service && sleep 2 && curl -sk -o /dev/null -w \"vpt-server: HTTP %{http_code}\" http://localhost:5109/health && echo'"
fi

echo "done."

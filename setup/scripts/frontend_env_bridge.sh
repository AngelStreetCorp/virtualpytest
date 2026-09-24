#!/bin/bash
# Forced SSH command for the Settings page's frontend .env bridge.
#
# Installed as a `command=` restriction on an authorized_keys entry (see
# docs/agent/validation/CONTRACTS.md #18b), so this is the ONLY thing that key
# can ever run on the frontend VM: "read" prints the current frontend/.env,
# "write" replaces it from stdin after taking a timestamped backup, "restart"
# restarts whichever frontend service is actually installed. Anything else is
# rejected.
set -euo pipefail

ENV_FILE="/opt/virtualpytest/frontend/.env"

case "${SSH_ORIGINAL_COMMAND:-}" in
  read)
    cat "$ENV_FILE"
    ;;
  write)
    cp "$ENV_FILE" "$ENV_FILE.backup.$(date +%Y%m%d_%H%M%S)"
    cat > "$ENV_FILE"
    ;;
  restart)
    if systemctl list-unit-files | grep -q '^vpt-frontend-prod\.service'; then
      sudo -n systemctl restart vpt-frontend-prod
    elif systemctl list-unit-files | grep -q '^vpt-frontend\.service'; then
      sudo -n systemctl restart vpt-frontend
    else
      echo "frontend_env_bridge: no vpt-frontend(-prod) service installed" >&2
      exit 1
    fi
    ;;
  *)
    echo "frontend_env_bridge: unsupported command" >&2
    exit 1
    ;;
esac

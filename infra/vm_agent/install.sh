#!/usr/bin/env bash
# Install (or update) the VirtualPyTest VM agent on one infra VM.
#
#   sudo ./install.sh --units nginx --allow 192.168.x.103
#   sudo ./install.sh --containers 'supabase_*' --allow 192.168.x.103
#   sudo ./install.sh --units minio,redis-server --allow 192.168.x.103
#
# --units       systemd units to report (comma-separated)
# --containers  docker container names or globs to report (comma-separated)
# --allow       client IPs allowed to read /status — the backend server(s)
# --port        listen port (default 9110)
# --action      optional action to enable (repeatable); only `db-backup` exists: lets the server ask
#               this VM for a fresh database backup. Needs --action-token-file.
# --action-token-file  file holding the shared secret the server sends (X-VM-Agent-Token). Its
#               content is copied into /etc/default/vpt-vm-agent, which is written 0600.
#
# With --action db-backup it also installs vpt-db-backup.service (not enabled, not started): the agent
# starts it on request. /usr/local/bin/vpt-db-backup.sh must already be there.
#
# Re-running rewrites /etc/default/vpt-vm-agent from the flags and restarts.
set -euo pipefail

UNITS="" CONTAINERS="" ALLOW="" PORT="9110" ACTIONS="" TOKEN_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --units) UNITS="$2"; shift 2 ;;
    --containers) CONTAINERS="$2"; shift 2 ;;
    --allow) ALLOW="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --action) case "$2" in db-backup) ;; *) echo "unknown action: $2 (only db-backup)" >&2; exit 2 ;; esac
              ACTIONS="${ACTIONS:+$ACTIONS,}$2"; shift 2 ;;
    --action-token-file) TOKEN_FILE="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

TOKEN=""
if [ -n "$ACTIONS" ]; then
  [ -n "$TOKEN_FILE" ] && [ -r "$TOKEN_FILE" ] || { echo "--action needs --action-token-file <readable file>" >&2; exit 2; }
  TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
  [ "${#TOKEN}" -ge 32 ] || { echo "the action token must be at least 32 characters (openssl rand -hex 32)" >&2; exit 2; }
  case "$TOKEN" in *[!A-Za-z0-9._~+=-]*) echo "the action token may only contain letters, digits and . _ ~ + = -" >&2; exit 2 ;; esac
elif [ -n "$TOKEN_FILE" ]; then
  echo "--action-token-file given without --action db-backup" >&2; exit 2
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
install -d -m 755 /opt/vpt-vm-agent
install -m 755 "$HERE/vpt_vm_agent.py" /opt/vpt-vm-agent/vpt_vm_agent.py
install -m 644 "$HERE/vpt-vm-agent.service" /etc/systemd/system/vpt-vm-agent.service

umask 077   # the file may hold the action token: root-only
cat > /etc/default/vpt-vm-agent <<CONF
# Written by infra/vm_agent/install.sh — re-run it to change these.
VM_AGENT_PORT=$PORT
VM_AGENT_ALLOW=$ALLOW
VM_AGENT_UNITS=$UNITS
VM_AGENT_CONTAINERS=$CONTAINERS
VM_AGENT_ACTIONS=$ACTIONS
VM_AGENT_ACTION_TOKEN=$TOKEN
CONF
chmod 600 /etc/default/vpt-vm-agent

if [ -n "$ACTIONS" ]; then
  # The backup runs as its own unit, outside the agent's sandbox. Installed, never enabled or started here.
  install -m 644 "$HERE/vpt-db-backup.service" /etc/systemd/system/vpt-db-backup.service
fi

systemctl daemon-reload
systemctl enable vpt-vm-agent >/dev/null
systemctl restart vpt-vm-agent
sleep 2
systemctl --no-pager --lines=0 status vpt-vm-agent | head -3
echo "Check: curl -s http://127.0.0.1:$PORT/status  (from an allowed IP if --allow is set)"

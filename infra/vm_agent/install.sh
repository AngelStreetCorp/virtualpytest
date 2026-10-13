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
#
# Re-running rewrites /etc/default/vpt-vm-agent from the flags and restarts.
set -euo pipefail

UNITS="" CONTAINERS="" ALLOW="" PORT="9110"
while [ $# -gt 0 ]; do
  case "$1" in
    --units) UNITS="$2"; shift 2 ;;
    --containers) CONTAINERS="$2"; shift 2 ;;
    --allow) ALLOW="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
install -d -m 755 /opt/vpt-vm-agent
install -m 755 "$HERE/vpt_vm_agent.py" /opt/vpt-vm-agent/vpt_vm_agent.py
install -m 644 "$HERE/vpt-vm-agent.service" /etc/systemd/system/vpt-vm-agent.service

cat > /etc/default/vpt-vm-agent <<CONF
# Written by infra/vm_agent/install.sh — re-run it to change these.
VM_AGENT_PORT=$PORT
VM_AGENT_ALLOW=$ALLOW
VM_AGENT_UNITS=$UNITS
VM_AGENT_CONTAINERS=$CONTAINERS
CONF

systemctl daemon-reload
systemctl enable vpt-vm-agent >/dev/null
systemctl restart vpt-vm-agent
sleep 2
systemctl --no-pager --lines=0 status vpt-vm-agent | head -3
echo "Check: curl -s http://127.0.0.1:$PORT/status  (from an allowed IP if --allow is set)"

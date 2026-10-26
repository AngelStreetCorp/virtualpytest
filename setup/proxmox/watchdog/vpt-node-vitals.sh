#!/bin/bash
# One vitals row per minute, pushed to proxmox3 so the minutes before a hang survive the reboot.
# Config in /etc/vpt-node-vitals.env or ~/.vpt-node-vitals.env: VITALS_TARGET=user@host, optional VITALS_KEY=path
for f in /etc/vpt-node-vitals.env "$HOME/.vpt-node-vitals.env"; do [ -r "$f" ] && . "$f"; done
: "${VITALS_TARGET:?set VITALS_TARGET}"; KEY=${VITALS_KEY:-$HOME/.ssh/vitals_ed25519}
load=$(cut -d' ' -f1-3 /proc/loadavg)
mem=$(awk '/MemAvailable/{a=$2}/MemTotal/{t=$2}/SwapFree/{sf=$2}/SwapTotal/{st=$2}END{printf "memavail=%dMB/%dMB swapused=%dMB",a/1024,t/1024,(st-sf)/1024}' /proc/meminfo)
psi=$(tr '\n' ' ' </proc/pressure/io 2>/dev/null | sed -E 's/ avg300=[^ ]+ total=[^ ]+//g')
dsk=$(df -P / 2>/dev/null | awk 'NR>1{printf "root=%s",$5}')
blk=$(awk '$3 ~ /^(nvme[0-9]n[0-9]|sd[a-z])$/ {printf "%s:inflight=%s ",$3,$12}' /proc/diskstats)
vm=$(awk '/^oom_kill /{printf "oom_kill=%s ",$2}' /proc/vmstat)
dstate=$(ps -eo stat= | grep -c '^D')
echo "$(date -u +%FT%TZ) load=$load dstate=$dstate $mem psi_io[$psi] $dsk $blk$vm" \
 | ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=5 "$VITALS_TARGET" 'cat >> /var/lib/vpt-node-watch/vitals' 2>/dev/null || true

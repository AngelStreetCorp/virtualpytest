#!/bin/bash
# Probes the main Proxmox node ($NODE_IP, from the env file) from proxmox3 every minute.
# State in /var/lib/vpt-node-watch; email via Resend after FAIL_AFTER consecutive failures, once per incident.
set -u
. /etc/vpt-node-watch.env
T=${NODE_IP:?set NODE_IP in /etc/vpt-node-watch.env}; ST=${STATE_DIR:-/var/lib/vpt-node-watch}; SUBJ=${SUBJ_PREFIX:-[VPT]}; FAIL_AFTER=${FAIL_AFTER:-3}
mkdir -p $ST; cd $ST
res=""; bad=0
chk(){ if eval "$2" >/dev/null 2>&1; then res+="$1=ok "; else res+="$1=FAIL "; bad=1; fi; }
chk ping "ping -c2 -W2 $T"
chk ssh "timeout 6 bash -c 'read -t5 l < /dev/tcp/$T/22 && [[ \$l == SSH-* ]]'"
# 8006 is firewalled from outside: logged for information only, never a failure
if timeout 6 bash -c "</dev/tcp/$T/8006" >/dev/null 2>&1; then res+="pve8006=ok "; else res+="pve8006=closed "; fi
chk health "curl -fsS -m 10 -o /dev/null https://virtualpytest.angelstreet.io/server/health"
echo "$(date -u +%FT%TZ) $res" >> probes.log
tail -n 2000 probes.log > probes.tmp && mv probes.tmp probes.log
n=$(cat fails 2>/dev/null || echo 0)
mail(){ curl -sS -m 20 https://api.resend.com/emails -H "Authorization: Bearer $RESEND_API_KEY" -H 'Content-Type: application/json' \
  -d "{\"from\":\"$RESEND_FROM_NAME <$RESEND_FROM_ADDRESS>\",\"to\":[\"$RESEND_TO_ADDRESS\"],\"subject\":\"$1\",\"text\":\"$2\"}" | grep -q '"id"'; }
if [ $bad = 1 ]; then
  n=$((n+1)); echo $n > fails
  if [ $n -ge $FAIL_AFTER ] && [ ! -f alerted ]; then
    [ -f down_since ] || date -u +%FT%TZ > down_since
    mail "$SUBJ Proxmox node DOWN ($T)" "Probed from proxmox3. $res — First failure ~$(cat down_since). Before restarting: check Hetzner Robot console/rescue, then read journalctl -b -1 and the last vitals in /var/lib/vpt-node-watch/vitals on proxmox3." && touch alerted
  fi
  [ -f down_since ] || date -u +%FT%TZ > down_since
else
  if [ -f alerted ]; then mail "$SUBJ Proxmox node RECOVERED" "All probes ok: $res — Down since $(cat down_since)." || exit 0; fi
  rm -f fails alerted down_since
fi

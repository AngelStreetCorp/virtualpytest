#!/usr/bin/env bash
# Apply the remote Pi live-stream cache to the proxy VM's nginx vhost, from a machine that can ssh to `proxy`.
#   bash infra/proxy/nginx/apply_pi_stream_cache.sh --dry-run    # show the diff only, change nothing
#   bash infra/proxy/nginx/apply_pi_stream_cache.sh               # backup, patch, nginx -t, reload (restores on a failed test)
# The two pieces come from config/example/pi-stream-cache.conf. Idempotent: does nothing if keys_zone=vpt_pistream exists.
# Rollback: cat ~/nginx-backup/virtualpytest.<stamp>.pre-pi-stream-cache > /etc/nginx/sites-enabled/virtualpytest; sudo nginx -t; sudo systemctl reload nginx
set -euo pipefail
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
HERE="$(cd "$(dirname "$0")" && pwd)"
VHOST=/etc/nginx/sites-enabled/virtualpytest
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
scp -q -o BatchMode=yes "proxy:$VHOST" "$WORK/vhost.orig"
if grep -q "keys_zone=vpt_pistream" "$WORK/vhost.orig"; then echo "already applied"; exit 0; fi
python3 - "$WORK" "$HERE/config/example/pi-stream-cache.conf" <<'PYEOF'
import sys
work, example = sys.argv[1], sys.argv[2]
s = open(work + '/vhost.orig').read()
ex = open(example).read()
p1 = ex.split('# --- 1.')[1].split('\n', 1)[1].split('# --- 2.')[0].rstrip() + '\n\n'
p2 = ex.split('# --- 2.')[1].split('----\n', 1)[1]
marker = 'upstream rpitest_origin {'
assert s.count(marker) == 1, 'upstream rpitest_origin not found once'
s = s.replace(marker, p1 + marker, 1)
gate = ' # Stream auth gate (BUG-0107 step 2, generalized)'
assert s.count(gate) == 2, 'expected the stream gate comment in both server blocks'
s = s.replace(gate, p2 + gate)
open(work + '/vhost.new', 'w').write(s)
PYEOF
diff -u "$WORK/vhost.orig" "$WORK/vhost.new" | head -200 || true
[ "$DRY" = 1 ] && { echo "(dry run: nothing changed)"; exit 0; }
STAMP="$(date +%Y%m%d-%H%M%S)"
ssh -o BatchMode=yes proxy "mkdir -p ~/nginx-backup && cp -p $VHOST ~/nginx-backup/virtualpytest.$STAMP.pre-pi-stream-cache"
scp -q -o BatchMode=yes "$WORK/vhost.new" proxy:/tmp/vhost.new.pistream
ssh -o BatchMode=yes proxy "cat /tmp/vhost.new.pistream > $VHOST && if sudo nginx -t; then sudo systemctl reload nginx && echo RELOADED; else cat ~/nginx-backup/virtualpytest.$STAMP.pre-pi-stream-cache > $VHOST; echo 'nginx -t failed: restored the backup, nothing reloaded'; exit 1; fi"
echo "applied; backup: ~/nginx-backup/virtualpytest.$STAMP.pre-pi-stream-cache"

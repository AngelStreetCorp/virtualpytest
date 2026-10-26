#!/usr/bin/env bash
# Apply the Timeline sprite cache (TASK-94) to the proxy VM's nginx vhost, from a machine that can ssh to `proxy`.
#   bash infra/proxy/nginx/apply_timeline_cache.sh --dry-run    # show the diff only, change nothing
#   bash infra/proxy/nginx/apply_timeline_cache.sh               # backup, patch, nginx -t, reload (restores on a failed test)
# On the proxy it uses only what user jndoye may do: write sites-enabled/virtualpytest, sudo nginx -t, sudo systemctl reload nginx.
# Idempotent: does nothing if proxy_cache_path vpt_timeline is already there.
# Rollback: cp ~/nginx-backup/virtualpytest.<stamp>.pre-timeline-cache /etc/nginx/sites-enabled/virtualpytest; sudo nginx -t; sudo systemctl reload nginx
set -euo pipefail
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
VHOST=/etc/nginx/sites-enabled/virtualpytest
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
scp -q -o BatchMode=yes "proxy:$VHOST" "$WORK/vhost.orig"
if grep -q "keys_zone=vpt_timeline" "$WORK/vhost.orig"; then echo "already applied"; exit 0; fi
cat > "$WORK/patch.py" <<'PYEOF'
import sys
S=sys.argv[1]
s=open(S+'/vhost.orig').read()
cache_path=r'''# TASK-94 Timeline: cache of the per-chunk thumbnail sprites the hosts serve under thumbnails/<hour>/timeline_*.
# The URLs are versioned (?v=<chunk end time>), so a cached file never goes stale; 26 h = the hosts' 24 h ring + margin.
# Only the timeline_* locations below use it. Size: ~29 MB per viewed device-day (worst ~70 MB), 3 GB holds ~40-100 devices.
proxy_cache_path /var/cache/nginx/vpt-timeline levels=1:2 keys_zone=vpt_timeline:10m max_size=3g inactive=26h use_temp_path=off;

'''
marker='upstream rpitest_origin {'
assert s.count(marker)==1
s=s.replace(marker,cache_path+marker,1)
common=r'''     proxy_cache vpt_timeline;
     proxy_cache_key "$uri$is_args$args";
     proxy_cache_valid 200 26h;
     proxy_cache_lock on;
     proxy_cache_use_stale error timeout updating http_502 http_504;
     proxy_ignore_headers Cache-Control Expires;
     proxy_hide_header Cache-Control;
     expires 1d;
'''
locs=r''' # TASK-94 Timeline sprites/tracks: same gate and upstream as the stream locations below, plus a read-through cache
 # (proxy_cache_path at the top of this file). Only timeline_* files under thumbnails/<hour>/; everything else on
 # /stream/ (HLS, live frames) is untouched. add_header is deliberately not used here (it would drop the server-level
 # security headers); a 200 is cached for 26 h, anything else (404 before the host built it) is not.
 location ~ ^/host/(vpt-pi[0-9]+|vpt-nipogi|vpt-mf1)/stream/(.+/thumbnails/[0-9]+/timeline_[A-Za-z0-9_]+\.(?:jpg|json))$ {
     set $pi_name $1;
     set $stream_path $2;
     auth_request /server/host-session/authorize;

     proxy_pass https://rpitest_origin/host/$pi_name/stream/$stream_path;
     proxy_ssl_name rpitest.angelstreet.io;
     proxy_http_version 1.1;
     proxy_set_header Connection "";
     proxy_ssl_server_name on;
     proxy_ssl_verify off;
     proxy_set_header Host rpitest.angelstreet.io;
     proxy_set_header X-Real-IP $remote_addr;
     proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
     proxy_set_header X-Forwarded-Proto https;
     proxy_read_timeout 60s;
     proxy_connect_timeout 10s;
'''+common+r''' }
 location ~ ^/host/([^/]+)/stream/(.+/thumbnails/[0-9]+/timeline_[A-Za-z0-9_]+\.(?:jpg|json))$ {
     set $host_identifier $1;
     set $stream_path $2;
     auth_request /server/host-session/authorize;

     proxy_pass http://$backend_host_ip:$backend_host_port/stream/$stream_path;
     proxy_set_header Host $host;
     proxy_set_header X-Real-IP $remote_addr;
     proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
     proxy_set_header X-Forwarded-Proto $scheme;
     proxy_read_timeout 60s;
     proxy_connect_timeout 10s;
'''+common+r''' }
'''
m2=' # Stream auth gate (BUG-0107 step 2, generalized)'
assert s.count(m2)==2
s=s.replace(m2,locs+m2)
open(S+'/vhost.new','w').write(s)
PYEOF
python3 "$WORK/patch.py" "$WORK"
diff -u "$WORK/vhost.orig" "$WORK/vhost.new" | head -150 || true
[ "$DRY" = 1 ] && { echo "(dry run: nothing changed)"; exit 0; }
STAMP="$(date +%Y%m%d-%H%M%S)"
ssh -o BatchMode=yes proxy "mkdir -p ~/nginx-backup && cp -p $VHOST ~/nginx-backup/virtualpytest.$STAMP.pre-timeline-cache"
scp -q -o BatchMode=yes "$WORK/vhost.new" proxy:/tmp/vhost.new.timeline
ssh -o BatchMode=yes proxy "cat /tmp/vhost.new.timeline > $VHOST && if sudo nginx -t; then sudo systemctl reload nginx && echo RELOADED; else cat ~/nginx-backup/virtualpytest.$STAMP.pre-timeline-cache > $VHOST; echo 'nginx -t failed: restored the backup, nothing reloaded'; exit 1; fi"
echo "applied; backup: ~/nginx-backup/virtualpytest.$STAMP.pre-timeline-cache"

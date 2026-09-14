#!/usr/bin/env bash
# Unauthenticated route sweep.
#
# Calls every probe-safe GET route (no path params, non-mutating) on a running
# server WITHOUT credentials and reports which answer 2xx. On a correctly
# secured deployment (ENFORCE_FRONTEND_JWT=true) every /server/* route except
# the documented unauthenticated exceptions must answer 401/403.
#
# Usage:
#   scripts/security/unauth_route_sweep.sh https://virtualpytest.angelstreet.io
#   FAIL_ON_LEAK=1 scripts/security/unauth_route_sweep.sh <base>   # exit 1 if any /server/* GET returns 2xx
#
# It parses routes straight from backend_server/src/routes/*.py so it stays in
# sync with the code. Read-only: it never sends POST/PUT/DELETE/PATCH.
set -euo pipefail

BASE="${1:-${BASE_URL:-http://localhost:5109}}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROUTES_DIR="$REPO_ROOT/backend_server/src/routes"

# Documented unauthenticated exceptions (mirror app.py unauthenticated_prefixes
# + health). A 2xx on these is expected and not a finding.
ALLOW_UNAUTH='^(/server/health|/server/auth/check|/server/mcp|/health|/docs/|/api/events/)'

routes="$(python3 - "$ROUTES_DIR" <<'PY'
import re, glob, os, sys
seen=set()
for f in sorted(glob.glob(os.path.join(sys.argv[1], '*.py'))):
    src=open(f, encoding='utf-8', errors='ignore').read()
    m=re.search(r"Blueprint\(\s*['\"][^'\"]+['\"]\s*,\s*__name__\s*(?:,\s*url_prefix\s*=\s*['\"]([^'\"]*)['\"])?", src)
    prefix=(m.group(1) if m and m.group(1) else '')
    for rm in re.finditer(r"@\w+\.route\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*methods\s*=\s*\[([^\]]*)\])?", src):
        path, methods = rm.group(1), (rm.group(2) or "'GET'")
        methods=[x.strip().strip("'\"").upper() for x in methods.split(',')]
        if 'GET' not in methods: continue
        full=(prefix.rstrip('/')+'/'+path.lstrip('/')) if prefix else path
        if '<' in full: continue          # skip path params (need a real id)
        if full not in seen:
            seen.add(full); print(full)
PY
)"

total=0; leaks=0
printf '%-6s %-10s %s\n' CODE BYTES PATH
printf '%s\n' '----------------------------------------------------------------'
while IFS= read -r p; do
  [ -z "$p" ] && continue
  total=$((total+1))
  tmp="$(mktemp)"
  code="$(curl -s -o "$tmp" -m 15 -w '%{http_code}' "$BASE$p" || echo 000)"
  bytes="$(wc -c < "$tmp" | tr -d ' ')"; rm -f "$tmp"
  flag=''
  if [[ "$code" =~ ^2 ]] && [[ "$p" == /server/* ]] && ! [[ "$p" =~ $ALLOW_UNAUTH ]]; then
    flag='  <-- UNAUTH 2xx'; leaks=$((leaks+1))
  fi
  printf '%-6s %-10s %s%s\n' "$code" "$bytes" "$p" "$flag"
done <<< "$routes"

echo
echo "swept $total GET routes against $BASE — $leaks unauthenticated 2xx on /server/*"
if [ "${FAIL_ON_LEAK:-0}" = "1" ] && [ "$leaks" -gt 0 ]; then
  echo "FAIL: $leaks route(s) served data without authentication" >&2
  exit 1
fi

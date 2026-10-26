#!/usr/bin/env bash
#
# Print the auto-sign test token, checked live, so an agent can sign in to any VirtualPyTest page or API.
#
#   T=$(scripts/agent/auto_sign_token.sh) || exit 1
#   curl -s -H "X-Auto-Sign: $T" https://<server>/server/system/getAllHosts
#   agent-browser open "https://<frontend>/<route>?auto_signed=$T"
#
# One token, kept in the main backend server's .env (AUTO_SIGN_TOKEN), works on every backend that trusts it:
# the main server and the vpt-pi1 server (rpitest) both answered 200 on 2026-10-15. Nobody needs sudo on a Pi.
# Owner rule (2026-10-15): fetching and using this test token is routine agent work, not an owner question.
# It is a team-admin credential: keep it in a shell variable, never print it, paste it in chat, a log, a doc or a commit.
#
# Env: AUTO_SIGN_SSH (ssh alias of the backend server VM, default "server"), AUTO_SIGN_CHECK_URL (base URL to check
# against, default the main server; "none" skips the check). Exit 1 with a reason on stderr when it cannot be had.
set -uo pipefail

SSH_ALIAS="${AUTO_SIGN_SSH:-server}"
CHECK_URL="${AUTO_SIGN_CHECK_URL:-https://virtualpytest.angelstreet.io}"

T="$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$SSH_ALIAS" \
  'sudo -n grep "^AUTO_SIGN_TOKEN=" /opt/virtualpytest/.env | tail -n 1 | cut -d= -f2-' 2>/dev/null | tr -d "\"'\r\n ")"
if [[ -z "$T" ]]; then
  echo "auto_sign_token: could not read AUTO_SIGN_TOKEN from $SSH_ALIAS:/opt/virtualpytest/.env (ssh alias or sudo -n missing)" >&2
  exit 1
fi
if [[ "$CHECK_URL" != "none" ]]; then
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 20 -H "X-Auto-Sign: $T" "$CHECK_URL/server/system/getAllHosts")"
  if [[ "$code" != "200" ]]; then
    echo "auto_sign_token: the token from $SSH_ALIAS was refused by $CHECK_URL (HTTP $code)" >&2
    exit 1
  fi
fi
printf '%s' "$T"

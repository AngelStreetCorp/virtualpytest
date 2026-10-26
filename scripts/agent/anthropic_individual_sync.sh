#!/usr/bin/env bash
# Wire the owner's Individual-org Anthropic key into node1's AI routing (second hop of every Claude chain, BUG-0721).
#
# The key is a user key (sk-ant-usr...). A workspace-scoped one works as is; an organisation-scoped one needs the
# workspace id (wrkspc_..., Console -> Workspaces) in codebox ~/.config/anthropic/individual.workspace. This script
#   1. copies key + workspace id into the server's secrets store (anthropic-individual, anthropic-individual-workspace),
#   2. makes one tiny call with them, and only if it answers
#   3. enables the anthropic-individual endpoint on the lab DB (the router picks it up within 30 s).
# Nothing is printed but names and the HTTP status. Run from the Mac: scripts/agent/anthropic_individual_sync.sh
set -euo pipefail

ws=$(ssh codebox 'tr -d " \n" < ~/.config/anthropic/individual.workspace 2>/dev/null || true')
# A workspace-scoped key needs no id; an organisation-scoped one does (the test call below tells).
if [[ -n "$ws" && ! "$ws" =~ ^wrkspc_ ]]; then
  echo "individual.workspace holds no wrkspc_ id: fix or empty it"
  exit 2
fi

store() {  # store <secret name>  (value on stdin)
  ssh server "sudo -u vpt_user bash -c 'cd /opt/virtualpytest && set -a && . ./.env && set +a && /opt/virtualpytest/venv/bin/python -c \"import sys; sys.path.insert(0, \\\".\\\"); from shared.src.lib.ai import secrets_store as s; s.set_secret(sys.argv[1], sys.stdin.read().strip())\" $1'"
}
ssh codebox 'tr -d "\n" < ~/.config/anthropic/individual.key' | store anthropic-individual
if [[ -n "$ws" ]]; then printf '%s' "$ws" | store anthropic-individual-workspace; fi
echo "stored: anthropic-individual${ws:+, anthropic-individual-workspace}"

# One tiny call with the stored key + workspace, on the server, counted in ai_calls as test:text like a Settings Test.
ssh server "sudo -u vpt_user bash -c 'cd /opt/virtualpytest && set -a && . ./.env && set +a && /opt/virtualpytest/venv/bin/python -'" <<'PY' || { echo "not enabling the endpoint"; exit 1; }
import sys, time
sys.path.insert(0, ".")
from shared.src.lib.ai import call_log, router
from shared.src.lib.ai.provider_client import connectivity_response, response_usage
from shared.src.lib.database import ai_routing_db
endpoint = next(e for e in ai_routing_db.list_endpoints() if e["name"] == "anthropic-individual")
hop = router.Hop(profile={"id": "", "name": "(test) claude-haiku-5-5", "model": "claude-haiku-5-5"}, endpoint=endpoint)
resolution, started = router.test_resolution(hop, "text"), time.time()
try:
    used = response_usage(connectivity_response(hop.client(), hop.model))
    router.record(resolution, hop, ok=True, ms=int((time.time() - started) * 1000), tokens_in=used.tokens_in,
                  tokens_out=used.tokens_out, usage=used)
    print(f"test call: ok, {used.tokens_in}/{used.tokens_out} tokens")
except Exception as e:
    router.record(resolution, hop, ok=False, ms=int((time.time() - started) * 1000), error_type="auth")
    print(f"test call failed: {type(e).__name__}")
    sys.exit(1)
finally:
    call_log.flush()
PY

echo "UPDATE public.ai_endpoints SET enabled = true, updated_at = now() WHERE name = 'anthropic-individual';" \
  | ssh proxmox "ssh 192.168.0.102 'PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U supabase_admin -d postgres -v ON_ERROR_STOP=1'"
echo "anthropic-individual enabled: Claude chain = AngelStreet key -> Individual key -> MiniMax"

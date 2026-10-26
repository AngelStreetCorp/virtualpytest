# BUG-0883 — Atlas cannot be routed to MiniMax M3.1-Flash: the profile declares no `tools` capability

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0883                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | backend / ai routing                                         |
| Fixed in  | —                                                            |
| Commit    | —                                                            |

---

## Symptom

The AI profile that serves MiniMax M3.1-Flash cannot answer Atlas, because the routing table refuses
a route to it:

```
POST /server/ai/routes
{"team_id": "7fdeb4bb-…", "usage_key": "agent.atlas",
 "profile_id": "7384547f-5742-4b55-b7d0-0ffb409d8432"}
→ HTTP 400 {"error": "Profile 'minimax-m3-1-flash' lacks tools required by 'agent.atlas'
            (run its Test to record capabilities)", "success": false}
```

The profile `minimax-m3-1-flash` (model `MiniMax-M3.1-Flash-Preview`, endpoint `minimax`) records
`capabilities: ["vision"]` only. `agent.atlas` needs `tools`
(`usages.needs('agent.atlas')`), so `_validate_route` in
`backend_server/src/routes/server_ai_routing_routes.py` rejects every route to it.

The model is also absent from the Atlas model picker: the dropdown lists the `agent.atlas` chain
only (AUTO, `atlas-fast` → `minimax-m2.7-highspeed`, `minimax-m3`, `openrouter-minimax-m3`), so a user
cannot choose M3.1-Flash in the UI either.

## Root cause

Two different things, both visible in the live configuration:

1. **The capability record is incomplete.** The same profile already serves `agent.forge` — a usage
   that needs `tools` — through route `0e3a62c6-…`, so the model does produce tool calls in
   production. The profile's declared capabilities were never updated to say so.
2. **Only a platform admin can record the capability.** Both ways of fixing it are
   `@require_platform_admin`: `POST /server/ai/profiles/<id>/test` (a live tool-call probe that
   records the capability on success) and `PUT /server/ai/profiles/<id>` (which would set
   `capabilities` by hand). The auto-sign test token is a **team admin**, not a platform admin
   (`GET /server/ai/config` → `"is_platform_admin": false`), so the agent/benchmark session cannot
   certify the profile itself.

## Fix

A platform admin runs the tool-call probe on the profile:

```bash
curl -X POST "https://virtualpytest.angelstreet.io/server/ai/profiles/7384547f-5742-4b55-b7d0-0ffb409d8432/test" \
  -H "X-Auto-Sign: <platform-admin token>" -H "Content-Type: application/json" \
  -d '{"kind": "tools"}'
```

On success the profile records `capabilities: ["tools", "vision"]`, and the route becomes acceptable:

```bash
curl -X POST "https://virtualpytest.angelstreet.io/server/ai/routes" \
  -H "X-Auto-Sign: <platform-admin token>" -H "Content-Type: application/json" \
  -d '{"team_id": "7fdeb4bb-3639-4ec3-959f-b54769a219ce", "usage_key": "agent.atlas",
       "profile_id": "7384547f-5742-4b55-b7d0-0ffb409d8432", "priority": 100, "enabled": true}'
```

(That route is a **team**-layer route, so it only changes how Atlas answers for this team; the
server-default layer is platform-super-admin only and was left untouched.)

## Verification

```bash
curl -H "X-Auto-Sign: $AUTO_SIGN_TOKEN" "https://virtualpytest.angelstreet.io/server/ai/config" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); \
      print([p for p in d['profiles'] if p['name']=='minimax-m3-1-flash'])"
```

`capabilities` must contain `tools`. A run pinned to the profile then reports the model the server
used:

```bash
scripts/atlas_usecase_bench.py --vars /tmp/vars.json --agents 10 \
  --pinned-profile 7384547f-5742-4b55-b7d0-0ffb409d8432 --model-label MiniMax-M3.1-Flash-Preview \
  --out /tmp/bench-flash.jsonl
```

Until the capability is certified, the benchmark scores M3.1-Flash through the **session pin**
(`pinned_profile_id`, the Atlas model picker), which resolves the profile without the route
validation — that is how the numbers in `docs/agent/atlas/USECASES.md` were taken.

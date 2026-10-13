# BUG-0450 — system-ops skill shipped 2 MCP tools that duplicated masterchief ops

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0450                                                     |
| Reported  | 2026-10-09                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | backend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | `ebdca9ad6` (merge: `fix/system-ops-dedupe`)                 |

## Symptom

The first commit of the system-ops skill (`70a1645fb`,
`feat/system-ops-skill`) shipped 4 MCP tools in
`backend_server/src/mcp/tools/system_ops_tools.py`:

- `list_services` — wrapped `GET /server/hosts/<host_name>/services`
- `restart_service` — wrapped `POST /host/system/controlService` (action=restart)
- `check_storage` — wrapped `GET /host/system/checkStorage` (new)
- `ping_host` — wrapped `GET /host/system/pingHost` (new)

Two of the four (`list_services` and `restart_service`) overlapped with
the masterchief agent (TASK-71) at the **operation** level, even though
the host routes they hit were different endpoints. From Atlas's point of
view, the user had two ways to ask "what services are running?" and two
ways to ask "restart vpt-stream" — and the two surfaces had different
security tiers.

The asymmetry:

| Op | Masterchief path | System-ops path |
| --- | --- | --- |
| `list_services` | `propose_masterchief_op(op='logs.services')` → confirm card + `masterchief_audit` row | direct MCP call, **no** confirm card, **no** audit row |
| `restart_service` | `propose_masterchief_op(op='service.restart', ...)` → confirm card + audit + prod `require_platform_admin` | direct MCP call, **no** confirm card, **no** audit row, **no** admin gate |

`service.restart` is the only mutating op in masterchief. Having a
second, unaudited path to it was exactly the `MCPAPIClient` service-key
bypass that TASK-71 was designed to close — the system-ops tools were
reachable from the same MCP proxy as everything else, and the proxy
honoured its service key.

## Repro

1. From a deployed backend_server (prod or dev), `GET
   /server/mcp-proxy/tools` (with the server's `X-API-Key`). The catalog
   included both `system_ops.list_services` and
   `masterchief.propose_masterchief_op` (which can dispatch
   `op='logs.services'` and `op='service.restart'`).
2. Call `system_ops.list_services` directly. It returns the same data
   that `propose_masterchief_op(op='logs.services')` would return, with
   no confirm-card step and no audit row written.
3. Call `system_ops.restart_service(host_name='vpt-pi3',
   service='vpt-stream')` directly. The service is restarted, again
   without a confirm card or an audit row.

## Root cause

The system-ops skill was scoped as "a small-ops surface for Atlas"
(TASK-73 Handover block, the original message: "get device info,
troubleshoot, restart services, check storage space"). The skill
authored in this session added `list_services` and `restart_service`
without checking whether masterchief already covered the same
operations. masterchief's doc explicitly states
`An op not in MASTERCHIEF_OPS is refused at every entry point` — but
that rule was for the masterchief surface, not for the entire system.
The shared authority ("which surface is allowed to do X") was not
enforced anywhere outside masterchief.

The host routes were different (`/host/restartHostService` vs
`/host/system/controlService` action=restart, etc.), so the duplication
wasn't a route-level bug — it was an op-level one. The fix does not
change any host route; it changes which surface Atlas calls.

## Fix

`backend_server/src/mcp/tools/system_ops_tools.py` — removed the two
duplicate methods. The class now exposes only `check_storage` and
`ping_host`. The docstring at the top documents the de-dupe and points
the reader at the Handover block in TASK-73 and at `propose_masterchief_op`
for any list / restart / status / log intent.

`backend_server/src/agent/skills/definitions/system-ops/SKILL.md` —
rewritten to make the read-only-host-health scope explicit. The
triggers, description, workflow, anti-patterns, and escalation all now
point at masterchief for every list / status / restart / log intent.
The "Do NOT shortcut masterchief" anti-pattern is in place: the skill
will not register any future `list_services` / `restart_service` /
`service.status` tool, and the escalation block tells the model to call
`propose_masterchief_op(...)` instead.

`tests/backend_server/test_mcp_system_ops.py` — the 5 tests for
`list_services` and `restart_service` were removed. The remaining 4
mcp tests (2 for `check_storage`, 2 for `ping_host`) plus the 4 host
route tests are the new test surface: 8 tests, all green.

`docs/tasks/TASK-73-atlas-testing-progressive.md` — Handover block
added at the bottom of the file recording the de-dupe (commit,
branch, worktree, VERSION.txt).

No changes to:
- masterchief (`backend_server/src/lib/masterchief/ops.py` and the
  `MASTERCHIEF_OPS` registry) — unchanged.
- The host routes (`/host/system/checkStorage`, `/host/system/pingHost`)
  — still the canonical implementations of `check_storage` and
  `ping_host`.
- `assistant.yaml` — the `system-ops` skill is still registered.

## Verify

- `python3 -m pytest tests/backend_host/test_host_system_ops_routes.py
  tests/backend_server/test_mcp_system_ops.py -q` → 8 passed.
- `grep -nE "def (list_services|restart_service)\("
  backend_server/src/mcp/tools/system_ops_tools.py` → no matches.
- `grep -nE "logs\.services|service\.restart" backend_server/src/agent/
  skills/definitions/system-ops/SKILL.md` → both names appear, but
  only as escalation pointers ("call `propose_masterchief_op(op=...)`").
- `GET /server/mcp-proxy/tools` after the next deploy will show
  `system_ops` with only `check_storage` and `ping_host` (the other
  two are gone from the catalog). The masterchief surface still
  exposes the same 7 ops; `propose_masterchief_op` is the only path
  to a service list / status / restart.

## Why this is a design rule, not just a one-off

masterchief's doc says the registry is the single source of truth
("An op not in `MASTERCHIEF_OPS` is refused at every entry point").
That rule is the *op-level* policy. The new rule, codified in the
system-ops SKILL.md anti-pattern block, is its mirror:

> If a new op is audit-worthy (mutates, or reads something sensitive,
> or needs `require_platform_admin` on prod), it goes in masterchief.
> Otherwise it can go in system-ops. The two surfaces do not overlap
> by design.

The asymmetry was the bug. The fix is the rule, plus the
de-duplication. Future "small-ops" requests will be checked against
the masterchief registry first; if the op exists there, the request
goes to masterchief and the system-ops tool is not added.

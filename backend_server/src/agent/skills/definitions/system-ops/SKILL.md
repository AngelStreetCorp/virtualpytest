---
name: system-ops
description: Read-only host health checks — "how much storage is left?", "is the host up?", "ping vpt-pi3", "df -h", "disk space on the pi". For mutating ops (list services, restart a service) use the masterchief agent (propose_masterchief_op), not this skill.
timeout_seconds: 60
requires_device: false
tools:
  - check_storage
  - ping_host
  - get_device_info
  - list_hosts
  - view_logs
  - capture_screenshot
triggers:
  - is the host up
  - is the host reachable
  - host up
  - host reachable
  - host down
  - connectivity
  - ping
  - ping host
  - storage
  - disk space
  - free space
  - how much storage
  - df -h
  - how much disk
  - disk usage
---

# System Operations — read-only host health

This skill is the **read-only host health** surface. It does NOT restart
services or list controllable services — those ops live in **masterchief**
(TASK-71, the confirm-card agent) and Atlas must call
`propose_masterchief_op` for them. Do not duplicate that surface here.

WORKFLOW — pick the right tool for the question:

1. For "is the host healthy" (the only thing this skill answers directly):
   a. `check_storage(host_name)` — df -h equivalent, one row per filesystem.
   b. `ping_host(host_name)` — TCP probe to the host's backend port.

2. For "what's wrong with this device" — defer to baseline tools (NOT in
   this skill, but listed here so you remember to call them first):
   a. `get_device_info(host_name, device_id)` — status, last seen, alerts.
   b. `capture_screenshot(device_id, host_name)` — see the current frame.
   c. `view_logs(host_name, service, lines=200)` — tail the service log.

3. For "list services" / "is X down" / "restart X" — this is masterchief.
   Call `propose_masterchief_op(op='logs.services' | 'service.status' |
   'service.restart' | 'host.disk_preview' | 'host.disk_cleanup', params={...})`. The user gets a confirm card and an
   audit row. This skill does NOT shortcut that flow.

ANTI-PATTERNS — do not do these, they break the masterchief contract:

- Do NOT shortcut masterchief by calling the host route directly. There
  is no `list_services` / `restart_service` tool in this skill on purpose.
  The mutating op is gated by `require_platform_admin` on prod and
  audited in `masterchief_audit`. Bypassing the card is exactly the
  `MCPAPIClient` service-key bypass TASK-71 closed.
- Do NOT loop `ping_host` more than once per turn — one answer is enough.
- Do NOT call `check_storage` on every filesystem; the route already
  filters to `/` on Linux. If the user really wants every mount, ask
  them to be specific.
- Do NOT call `run_command` — that is admin-gated and out of scope.

OUTPUT FORMAT — prefer the helper icons:

- ✅ running / ok / reachable
- 🔴 failed / stopped / unreachable
- ⚠️ degraded / unknown

If the tool is admin-gated and the user is not admin, say so explicitly
and point at Settings → Roles where an admin can grant the tool. Do not
pretend the operation succeeded.

ESCALATION — when none of these tools answer the question, hand off:

- "Restart vpt-stream" → `propose_masterchief_op(op='service.restart',
  params={'host': '<host>', 'service': 'vpt-stream'})` — the user gets
  a confirm card.
- "List services on vpt-pi3" → `propose_masterchief_op(op='logs.services')`.
- "View the application log" → `view_logs(service='<vpt-* name>')` first;
  if that returns no rows, ask the user which service they meant.
- "Reboot the host" → admin dashboard → rebootHost (admin only).

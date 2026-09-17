# BUG-0128 — Every /api/events route answered 500 because the router called the registry with one argument too many

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0128                                                                    |
| Reported  | 2026-09-16 (found while verifying [BUG-0126](BUG-0126-2026-09-16-runtime-route-background-loop-kills-atlas-chat.md)) |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (event publishing and all three alert shortcuts were unusable)       |
| Area      | `backend_server/src/events/event_router.py`                                 |
| Fixed in  | build 9151                                                                  |
| Commit    | `4480b0275d`                                                                |

---

## Symptom

`POST /api/events/publish` — and the three shortcuts `/api/events/alerts/blackscreen`,
`/api/events/alerts/device-offline`, `/api/events/builds/deployed` — answered **HTTP 500**:

```json
{"error":"AgentRegistry.get_agents_for_event() takes 2 positional arguments but 3 were given"}
```

for any well-formed body. No event was ever routed or logged.

## Root cause

`EventRouter.route_event` called `self.registry.get_agents_for_event(event.type, event.team_id)`,
but `AgentRegistry.get_agents_for_event(self, event_type)` takes only the event type — the
registry holds *system* agents, which are not team-scoped.

It survived because the route tests (`tests/backend_server/test_events.py`) only assert the
validation path: each posts a deliberately incomplete body and checks for 400, which returns
before the router is reached. No test ever posted a valid event.

## Fix

`4480b0275d` drops the extra argument, with a comment recording why it cannot be team-scoped.

## Verification

```
POST /api/events/publish {"type":"test.probe","payload":{"ok":true}}
-> 201 {"event_id":"evt_…","routed":false}
journal: [@router] ⚠️ Unhandled: test.probe (no agents registered)
```

Verified on `.103` 2026-09-16. `routed:false` is correct — no system agent subscribes to that
type.

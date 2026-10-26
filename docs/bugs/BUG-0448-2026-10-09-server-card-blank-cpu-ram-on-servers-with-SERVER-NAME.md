# BUG-0448 — Dashboard "Server" card shows no CPU/RAM/Disk on every deployment that sets `SERVER_NAME`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0448                                                                    |
| Reported  | 2026-10-09 (operator on the Dashboard, ssh server `virtualpytest.angelstreet.io`) |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (no resource visibility on the affected server card; collap­sible "Server Services" stays empty for the resource chips once the UI moves them) |
| Area      | `backend_server/src/lib/server/gunicorn_app.py`, `frontend/src/pages/Dashboard.tsx` |
| Fixed in  | build 90145 |
| Commit    | TBD                                                                         |

---

## Symptom

On the Dashboard, the per-server card on `virtualpytest.angelstreet.io` (the "ssh server") shows
the URL, the version line, the "Server Services" accordion, the host and device chips and the
restart/reboot buttons — but **no CPU / RAM / Disk / °C / Load chips**. The API server card
right above it (e.g. `<gateway-ip>`) shows all five chips fine. The two cards look identical in
every other way.

```
`<gateway-ip>`           main-2026.10.09-10418   CPU: 39%  RAM: 47%  Disk: 36%  63°C  Load: 4.3
virtualpytest.angelstreet.io   main-2026.10.09-10450                       (no chips)
```

Only one server is affected: the one whose `SERVER_NAME` env var is not literally the string
`server`. (Every `.env` template in the repo sets a real name — `hetzner1`, `vpt-docker`,
`Awesomation`, `vpt` — so this is the common case, not the rare one.)

After the dashboard move that puts the resource chips inside the collapsible "Server Services"
header, the symptom is the same on the new location: the accordion opens fine and the
"online" chip is there, but the chips on its right stay empty for any server that sets
`SERVER_NAME`.

## Root cause

Two halves of the same system_stats path were using two different keys for the metrics row in
`system_metrics`:

- **Store** (`backend_server/src/lib/server/gunicorn_app.py`, the `_collect_server_metrics`
  background thread that runs every minute) — hardcoded:

  ```python
  store_system_metrics('server', server_stats)
  ```

- **Read** (`backend_server/src/routes/server_system_routes.py`, `getAllHosts` when
  `include_system_stats=true`) — env-var driven:

  ```python
  latest_server_stats = get_latest_system_metrics(os.getenv('SERVER_NAME', 'server'))
  ```

Every other place in the backend that talks to a per-server identity uses
`os.getenv('SERVER_NAME') or 'server'` (see `server_utils.py`, `infra_status_collector.py`,
`server_auth_routes.py`, `server_report_snapshots_routes.py`, …). The store is the only caller
still pinning `'server'`.

On the API server (`<gateway-ip>`) the env var is unset, so the default `'server'` matches the
hardcoded store and the read returns the row. On the ssh server, `SERVER_NAME` is a real name,
the store still writes under `host_name='server'`, and the read queries a different
`host_name` and gets `None`. `server_info.system_stats` is then never set, the React conditional
`{serverData.server_info.system_stats && (…chips…)}` skips the whole chip block, and the card
shows nothing.

## Fix

1. **`gunicorn_app.py`** — key the metrics row by the same env var the read uses:

   ```python
   metrics_host_name = (os.getenv('SERVER_NAME') or '').strip() or 'server'
   success = store_system_metrics(metrics_host_name, server_stats)
   ```

   The `.strip()` matches the convention in the rest of the backend. Comment in the file points
   future readers at the read side so the two never drift apart again.

2. **`Dashboard.tsx`** — the original report was actually two asks in one ("move the chips to
   the right of 'online' in the collapsible header" + "why don't they show on the ssh server").
   Both landed in the same change:

   - The CPU / RAM / Disk / °C / Load chips moved out of the URL row (the row was already
     getting crowded: URL + version + chips + host chip + device chip + two icon buttons) and
     into the `<AccordionSummary>` of the collapsible "Server Services" header. The summary
     `content` is now a flex `space-between` row: "Server Services (4)" + "online" chip on the
     left, the resource chips on the right (and the expand chevron stays on the far right of
     the accordion as before).
   - The chips remain gated on `serverData.server_info.system_stats`. On the ssh server, the
     first paint after deploy will still show no chips — the metrics collector writes a fresh
     row at the top of the next minute — but the layout is now in place and stable.

## Verification

- `cd backend_server && python3 -c "import ast; ast.parse(open('src/lib/server/gunicorn_app.py').read())"` — clean.
- `cd frontend && ./node_modules/.bin/tsc --noEmit` — clean (file compiles against the existing
  `system_stats` type already used in the same component).
- Manual check after deploy:
  1. On the affected ssh server, `tail` `backend_server/logs/server.log` and confirm the next
     `[@backend_server:metrics] 📊 Server metrics collected and stored` line lands. (The
     collector takes 15 s to start after a worker boot and then runs once per minute.)
  2. Hit `GET /server/system/getAllHosts?include_system_stats=true` against the same server —
     `server_info.system_stats` is now non-null and contains the live CPU/RAM/Disk/°C/Load
     snapshot.
  3. Reload the Dashboard. The collapsible "Server Services" row now shows the resource chips
     on the right of the "online" chip, in the same colour treatment as the API server card.
  4. The API server card (whose `SERVER_NAME` is unset) still shows the chips — no behaviour
     change there.

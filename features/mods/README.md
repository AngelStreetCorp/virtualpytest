# mods

Small add-ons that hook app events and draw into core slots, like Claude Code mods. Full guide:
[docs/agent/platform/MODS.md](../../docs/agent/platform/MODS.md). Task: [TASK-77](../../docs/tasks/TASK-77-frontend-mods.md).

## Parts

- `frontend/routes.tsx` — the mod list (`mods: [...]`), the `/configuration/mods` page, its Settings nav entry.
- `frontend/manager/` — Settings > Mods: one card and switch per mod; saved to the user's account
  (`user_mod_preferences`), or kept in the browser for a shared login (localStorage `virtualpytest:mods:enabled`).
- `frontend/runProgress/` — Run Progress: band under the top bar, side pane with one row per running script /
  campaign / test case, toast when a run ends.
- `frontend/onlineUsers/` — Online Users: "N online" in the top bar, who in the tooltip (core `/system` presence).
- `frontend/pip/` — Picture-in-picture: a chosen device's stream bottom-right on every page; Take control shows
  its remote (stream moves bottom-left); pauses while a page controls a device.
- `frontend/splitView/` — Split view: a second page side by side (this app in a frame, `isEmbedded`); top-bar
  button or Ctrl + Alt + S; drag the divider, swap sides.
- `frontend/teamDevices/` — Team devices: a Dashboard widget with the team's devices, tests running and errors
  (failed runs in 24 h or 7 days, or open alerts: the widget's "Count as errors" setting).
- `frontend/blastRadius/` — Blast Radius: confirm dialog before a device is powered off or rebooted (the
  `device.command` gate asked by `usePowerControl`).

- `backend_server/` — `GET /server/mods/snapshot` (current runs, locks, presence as `system_update` events),
  `GET`/`PUT /server/mods/preferences`, `GET`/`PUT /server/mods/widgets`.
- `lib/` — `snapshot.py`, `mods_db.py`, `widget_layout.py` (layout shape check).
- `db/001_user_mod_preferences.sql`, `db/002_user_widget_layouts.sql` — **not applied by any deploy script**: run
  them on every database first.

## Core hooks relied on

`frontend/src/mods/core/` (registry, `ModsProvider`, `ModSlot`, `ModPaneDrawer`), `FeatureDefinition.mods` +
`featureMods()` in `frontend/src/config/features.ts`, the `app.band` / `app.pane` slots in `App.tsx`, and the
`/system` socket events (core/mappers.ts), the `useModGate()` call in `frontend/src/hooks/power/usePowerControl.ts`, the `/system` team rooms and
presence in `backend_server/src/routes/server_system_socket_routes.py` + `backend_server/src/lib/socket_presence.py`,
`task_manager.running_tasks()`, the `control.change` emit in `frontend/src/hooks/useDeviceControl.ts`, the
`app.overlay` / `app.side` slots, embedded mode (`frontend/src/utils/embeddedMode.ts`, `App.tsx`), the widget area
(`frontend/src/mods/core/components/widgets/`, mounted in `pages/Dashboard.tsx`) and `positionRight` on `HDMIStream` / `VNCStream` / `DeviceControlPanels`.

## Tests

- `cd frontend && ./node_modules/.bin/vitest run --root .. features/mods frontend/src/mods`
- `pytest tests/backend_server/test_system_socket_rooms.py tests/backend_server/test_mods_snapshot.py tests/backend_server/test_mods_widget_layout.py` (offline, unit)

## Disable

`DISABLED_FEATURES=mods`: no mod loads, the Mods page and nav entry are gone, no extra socket opens.

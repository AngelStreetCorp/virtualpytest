# BUG-0047 — Rec lock badge/tooltip shows either who is running a script or the script name, never both

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0047                                                     |
| Reported  | 2026-09-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (display only; lock behavior itself is correct)          |
| Area      | `backend_server/src/lib/utils/lock_utils.py`, `backend_server/src/routes/server_script_routes.py`, `backend_server/src/routes/server_campaign_execution_routes.py`, `frontend/src/hooks/rec/useDeviceScriptLabel.ts`, `frontend/src/components/rec/*` |
| Fixed in  | build 8713                                                   |
| Commit    | `9de8c8dd4`                                                         |

---

## Symptom

On the Rec grid preview card and the Rec stream modal, the bottom-right badge and the
lock-icon tooltip show only one label at a time: when a script is launched while a user
already holds the device (take-control), the badge shows the user's name
(`Provisioning_Platform`) — the script that is actually running is nowhere to be seen. When no
user holds the device, the badge instead shows only the script name with no indication
of who started it.

## Root cause

A script launched while a user holds manual control runs *under* that user's lock —
`DeviceLockManager.acquire_lock` (`lock_utils.py`) takes the `allow_same_user_takeover`
branch and deliberately keeps `owner_type: 'manual_control'` so the lock isn't
reassigned mid-run, but it never recorded *what* started. The only lock metadata was
the manual lock's own `lock_reason` (`'manual_take_control'`), so the frontend had
nothing but the user's name to display.

`useDeviceScriptLabel` and `useDeviceLockLabel` then each derived a single label from
the same lock and the components (`RecHostPreview`, `RecHostStreamModal`,
`RecStreamModalHeader`) rendered `hasNamedDeployment ? script : manualControlLabel ?
user : null` — an either/or by construction, even once the data existed to show both.

Separately, `server_campaign_execution_routes.py` set `lock_reason=f"campaign_execute:
{campaign_id}"` — a bare UUID, which the frontend's UUID filter (correctly) drops as a
display label, so a running campaign showed no name at all, with or without a
manual-control umbrella.

## Fix

- `lock_utils.py`: the subordinate-acquire branch (script/campaign launched under an
  existing `manual_control` lock) now also records `active_script_reason` /
  `active_script_job_id` on the lock, serialized into `lock_info`. New
  `clear_active_script()` (module wrapper `clear_device_active_script()`) removes just
  that annotation — job-scoped, so a finished run can't clobber a newer run's label —
  while leaving the manual lock itself untouched. Every ownership transfer (takeover,
  same-user/same-IP takeover, `takeover_lock`) explicitly clears any stale annotation.
- `server_script_routes.py` / `server_campaign_execution_routes.py`: forward the
  caller's `user_name` onto the lock so a plain (non-subordinate) script/campaign lock
  also carries who launched it; call `clear_device_active_script()` (and emit
  `lock_changed`) on completion and on both launch-failure paths instead of only
  releasing the lock. Campaign `lock_reason` now uses the campaign **name**, falling
  back to the id only if no name was supplied.
- `mcp/tools/device_tools.py`: exposes `lock_owner_name` / `active_script_reason` so MCP
  callers see the same information.
- Frontend: `useDeviceScriptLabel` also reads `active_script_reason` and returns a new
  `scriptOwnerName`; `RunningScriptNameBadge` accepts an `ownerName` alongside
  `scriptName` and renders both (`owner · script`, each truncated on its own budget so
  the script name — the part that changes — isn't the one that gets eaten).
  `RecHostPreview`, `RecHostStreamModal`, `RecStreamModalHeader` now show a
  `Controlled by:` / `Run by:` line **and** a `Script:` line in the tooltip, and pass
  both to the badge, instead of picking one.

## Verification

- Exercised `DeviceLockManager` directly (no server): manual lock acquired by
  `Provisioning_Platform` → subordinate script acquire keeps `owner_type=manual_control`,
  `owner_user_name=Provisioning_Platform`, and records `active_script_reason=
  script_execute:goto_live`; a stale/older job id could not clear the annotation;
  the real job's completion cleared it while the manual lock and its owner survived.
- `tsc --noEmit` and `eslint` clean on every changed frontend file.
- Not yet re-verified against a real running script on a device in the browser
  (pending deploy).

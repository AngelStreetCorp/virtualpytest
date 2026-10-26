---
title: vpt-windows android_mobile controller fixes (launch_app, get_installed_apps, list_actions, tap alias, error hint)
area: device-control
severity: blocker
status: resolved
date: 2026-10-17
component: backend_host/src/controllers/remote/android_mobile.py
hosts: [vpt-windows]
device: Mobile_Emulator
related: [BUG-0588]
---

# BUG-0591: vpt-windows android_mobile controller fixes

## Problem

After BUG-0588 brought the Mobile_Emulator HLS pipeline up on vpt-windows, exercising
vpt-take-control commands exposed four controller-level bugs that all manifest as silent or
near-silent failures:

1. `get_installed_apps` → `{"error":"Object of type AndroidApp is not JSON serializable","success":false}`.
2. `launch_app` with `package_name=com.android.settings` → `{"message":"Command launch_app failed","success":false}` (the controller reads `params.get('package')` only — `package_name` is the form documented everywhere else).
3. `tap` (the form agent prompts naturally use) → `Invalid command 'tap' for android_mobile device. ... Did you mean 'click_element' (text-based) instead of 'click_element_by_index'?` — both `tap` and `click_element_by_index` don't exist; the error hint points at a non-existent command.
4. `list_actions` (also referenced in the error hint as "Use list_actions() to see all available commands") → not implemented; the call falls into the same unknown-command branch and the hint points to itself.

## Fix

`backend_host/src/controllers/remote/android_mobile.py`:

- `get_installed_apps` now projects each `AndroidApp` to a dict of `package_name / app_name / version_name / is_system_app` before returning, so the response survives `json.dumps`. `success` is `True` when any app is returned, plus a `count` field for cheap client-side validation.
- `launch_app` accepts both `package` (canonical, MCP / original API) and `package_name` (docs / agent prompts). Missing both returns a clear `"launch_app requires 'package' or 'package_name' parameter"` error.
- `tap` is added as an alias for `tap_coordinates` (same `x`/`y`/`x_pct`/`y_pct` semantics, same error messages). Documented in EMULATOR.md under "Tap — px or % of the live screen".
- `list_actions` is now a real command returning a 16-entry list with one-line parameter descriptions, sourced from the actual `execute_command` handler so the two cannot drift.
- The unknown-command error message replaces the static `"Did you mean 'click_element' (text-based) instead of 'click_element_by_index'?"` hint with a Levenshtein-distance nearest-match against the live valid-commands list (bounded; pure-Python). If no candidate is within `max(3, len(command)//3)`, no hint is shown. `'taap'` → `"Did you mean 'tap'?"` (verified). The "Use list_actions() to see all available commands" line is preserved (and now actually works).

## Verification (live, 2026-10-17 13:30 UTC, vpt-windows PID 18552)

| Command | Pre-fix | Post-fix |
|---------|---------|----------|
| `list_actions` | 404-style "Invalid command" | 16 actions, `success: true` |
| `get_installed_apps` | `Object of type AndroidApp is not JSON serializable` | `success: true, count: 17, apps: [{package_name, app_name, version_name, is_system_app}, ...]` |
| `launch_app` (`package_name`) | `Command launch_app failed` | `Command launch_app executed successfully` |
| `launch_app` (`package`) | works | still works |
| `tap` | `Invalid command 'tap'` | `Command tap executed successfully` |
| `tap_coordinates` | works | still works |
| `taap` (typo) | wrong hint pointing at non-existent `click_element_by_index` | `Did you mean 'tap'?` |

End-to-end check: `launch_app` with `package=com.android.settings` actually opens the Settings
UI. Verified via `take_screenshot` (1080×1920 PNG at `/tmp/ai_screenshot_latest.png` shows
"Settings / Search settings / Network & internet / Connected devices / Apps / Notifications /
Battery 100% / Storage 30% used - 5.59 GB free / Sound & vibration / Display / …") and
`dump_elements` (35 elements, FrameLayout + TextView + ImageView in the right structure).

## Files

- `backend_host/src/controllers/remote/android_mobile.py` — `launch_app` accepts both
  `package` and `package_name`; new `tap` alias handler; new `list_actions` handler returning a
  16-action catalogue; `get_installed_apps` projects `AndroidApp` to JSON-safe dicts; the
  unknown-command branch now uses a Levenshtein nearest-match hint.
- `docs/agent/devices/EMULATOR.md` — added the **vpt-windows Native Emulator** section
  (topology, `.env`, bring-up recipe, `run_ffmpeg.ps1` source types, the adb-pair
  requirement, the vpt-take-control command cheatsheet, the 5 failure modes with their dashboard
  signatures, the port + firewall reference) and the 2026-10-17 BUG-0588 incident entry.

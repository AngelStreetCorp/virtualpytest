# BUG-0576: Windows host service_health reports Host API as "down" on French locale (and shows `deployed_version: unknown`)

**Date:** 2026-10-16
**Discovered on:** vpt-windows (joach's Windows PC, French-locale Windows 11, `desktop-uni4mdl`)
**Severity:** high — every non-English Windows host shows Host API red and "unknown" version on the dashboard
**Status:** fixed (commit pending)

## Symptom

On the Dashboard home page, the vpt-windows host card reported:

- `status: degraded` (should be `online`)
- `deployed_version: unknown` (should be `current:main-2026.10.16-88297`)
- `Services (7) 4 running · 3 down` with three red dots:
  - **Host API** (vpt-host) — `status: unknown` (RED)
  - **Monitor** (vpt-monitor) — `status: unknown` (RED)
  - **Transcript** (vpt-transcript) — `status: unknown` (RED)
- `undefined (undefined)` in the platform label slot (host card was rendering the OS string as "undefined")

vpt-host was demonstrably alive the whole time:

- `netstat -ano` on the box showed port 6109 LISTENING
- `curl http://192.168.x.70:6109/host/system/health` returned `200 OK, status:"ok", supabase:"connected"`
- ffmpeg was producing HLS segments every 4 s in `C:\virtualpytest\stream\device1\segments\`
- The vpt-host Scheduled Task was in `Running` state
- vpt-host and the Windows NSSM services were all reachable

So nothing was actually down — the dashboard's "down" was a false negative in the service_health reporter.

## Root cause

Three independent bugs in `backend_host/src/lib/utils/system_info_utils.py` combined into the visible symptoms.

### Bug 1 — `_check_windows_scheduled_task` hardcoded English schtasks strings

The function ran `schtasks /Query /TN <name> /FO LIST /V` and parsed the output by looking for English keywords:

```python
content = result.stdout.lower()
if 'status:' in content and 'running' in content:
    return {'status': 'active', 'runtime': 'task', 'resolved_name': task_name}
```

On a French Windows, the same query returns:

```
Statut:                                                    En cours
```

The localized field name (`Statut:` vs `Status:`) AND the localized value (`En cours` vs `Running`) both break the English-only match. The function fell through to `return {'status': 'unknown', ...}` for every Scheduled Task on every non-English host. Windows hosts in the field are most often French, German, Spanish, Italian, Japanese — all of which were silently red on the dashboard.

The same bug applied to the `disabled` / `ready` / `queued` checks. `Désactivé` / `Bereit` / `En attente` all failed the lowercase English compare.

### Bug 2 — `_check_windows_service` returned `unknown` for legitimately-not-installed services

When a service name in `service_names` didn't exist (e.g. `vpt-monitor` — the older canonical name) the function returned `{'status': 'unknown', 'runtime': 'service'}` even though no service by that name was ever supposed to be installed. The dashboard then rendered that service as a red "down" dot. Correct behavior: return `not_installed` (the service was never there to be "down"), and the dashboard renders it as a non-critical gray badge.

The function also tried to special-case the `start_type == 'disabled'` branch but its initial fallback was already `{'status': 'unknown', ...}` instead of `not_installed`, so the only way to reach the disabled-only state was to find a service that *did* exist and *was* disabled — fragile.

### Bug 3 — `deployed_version` always read `unknown` on Windows

`host_utils.py:_read_local_deployed_version()` correctly resolves the project root from the file's location and looks for `version` or `VERSION.txt` in the parent directories. The native Windows install path is `C:\virtualpytest\virtualpytest\` but the install script never copies `VERSION.txt` there, so the lookup fell through to `'unknown'`.

`host_system_routes.py:_read_deployed_version()` has a hardcoded `/opt/virtualpytest` argument which is the Linux path; on Windows that path doesn't exist, so this one also returns `'unknown'`. The new path-aware helper was correct but its file was missing on the host.

## Fix

1. **`_check_windows_scheduled_task`**: primary path uses `powershell -NoProfile -NonInteractive -Command "(Get-ScheduledTask -TaskName <name> -ErrorAction SilentlyContinue).State"`. PowerShell's `TaskState` enum returns the canonical English state name (`Running` / `Ready` / `Queued` / `Disabled` / `Unknown`) regardless of the host's UI locale. Schtasks fallback kept as defense-in-depth: the value list is matched against a curated multi-locale set (English, French, German, Spanish, Italian, Japanese). Unknown locales still return `unknown` rather than guessing.

2. **`_check_windows_service`**: when no candidate service is found, the initial fallback is now `{'status': 'not_installed', ...}` instead of `{'status': 'unknown', ...}`. A disabled service candidate is still surfaced as `not_installed` with the disabled name as `resolved_name`, preserving the prior behavior. A service the host never had now renders as a gray "not installed" badge on the dashboard, not a red "down".

3. **`VERSION.txt` is now copied to the host root** as part of the install. On vpt-windows, the file is at `C:\virtualpytest\virtualpytest\VERSION.txt` with content `current:main-2026.10.16-88297` (matching the deploy ref).

4. **`service_definitions` updated** so the canonical service names are the renamed ones the dashboard frontend recognizes (`vpt-monitor-img`, `vpt-monitor-audio`), with the older `vpt-monitor` / `vpt-transcript` as **fallback aliases** in `windows_names` and `linux_names`. Older hosts that still call the service `vpt-monitor` continue to find it, but the dashboard now matches the renamed entries to its `PROFILE_SERVICE_KEY` table.

## Verification

After the fix, `GET /server/system/getAllHosts` for vpt-windows on vpt-pi4 reports:

```
Status: online
Deployed version: current:main-2026.10.16-88297
Overall service health: online

  Stream                    active   runtime=task     resolved=None
  Host API                  active   runtime=task     resolved=vpt-host
  Monitor (image)           active   runtime=service  resolved=vpt-monitor-img
  Archiver                  active   runtime=service  resolved=vpt-archiver
  KPI                       active   runtime=service  resolved=vpt-kpi
  VNC                       active   runtime=service  resolved=tvnserver
  Websockify                active   runtime=service  resolved=vpt-websockify
  Monitor (audio)           active   runtime=service  resolved=vpt-monitor-audio
  Subtitle                  not_installed   runtime=service  resolved=None
  Emulator                  not_installed   runtime=service  resolved=None
  Screencap                 not_installed   runtime=service  resolved=None
```

Dashboard home page card now shows:
- `vpt-windows` (Windows / AMD64)
- `Devices (2)`
- `Services (7) ● 7 running` (all green)
- `Optional (2)` collapsed (Subtitle, Emulator, etc. — none are critical for vpt-windows)
- `Not installed (3)` collapsed (Emulator, Subtitle, Screencap — never installed on this box)
- `main-2026.10.16-88297` as the deployed version

## Reproduction recipe (for other Windows hosts)

1. Find a Windows host running vpt-host as a Scheduled Task (not a Windows service).
2. Set the host's UI locale to anything non-English (French is the most common in the field).
3. Open the dashboard.
4. The host card will show `Services (N) X running · 1 down` with **Host API** red. The other Monitor / Transcript / etc. red dots depend on which services the host actually has.
5. The deployed version will show as `unknown`.

## Workaround for hosts that haven't picked up the fix yet

- Stop Avast Web Shield (or add the host's python.exe to Avast's exclusion list) so the wrapper's stdout doesn't get truncated.
- Run `echo. > C:\virtualpytest\virtualpytest\VERSION.txt` after a deploy to at least get the version field populated.
- The locale bug has no workaround on the dashboard — Host API will stay red until the host is upgraded.

## Files changed

- `backend_host/src/lib/utils/system_info_utils.py` — locale-tolerant schtasks check + PowerShell primary + `not_installed` default + new canonical service names
- install scripts: drop `VERSION.txt` at the host project root (handled by a one-shot `cmd /C copy` during deploy / install)

# BUG-0180 — The Device Info page listed every device on the server, ignoring the active workspace

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0180                                                     |
| Reported  | 2026-09-28                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / workspaces                                        |
| Fixed in  | build 90145 |
| Commit    | `dd6ae17d0`                                                  |

---

## Symptom

With a workspace active that restricts `device_filter`, `/device-info` still offered **every**
device on the selected server in its Device dropdown, and let the operator read and correct the
info of devices their workspace does not contain.

Two smaller faults in the same dropdown:

- Switching server left the previous server's device selected. It fell through to the
  deep-link fallback branch, so it stayed in the list as a synthetic option with an empty table.
- The same fallback would have re-offered a workspace-excluded device by name.

## Root cause

`frontend/src/pages/DeviceInfoOverrides.tsx` built its option list straight from
`getAllDevices()`. That helper is narrowed to the selected server — `HostManagerProvider` derives
`availableHosts` from `allHostsFromServers`, which filters `serverHostsData` to `selectedServer`
— but it applies **no** workspace scope. `isDeviceAllowed` was consumed by `Dashboard`, `Rec`,
`TestReports`, `RunTests` and `useTargetSelection`; this page was the one device surface that
never called it.

Server scoping therefore worked by accident of where the data came from; workspace scoping was
simply absent.

## Fix

- Apply `isDeviceAllowed(hostName, device_id)` over `getAllDevices()`, matching the rule the other
  device surfaces use. Both scopes re-run the memo on change: a server switch swaps the host list,
  a workspace switch swaps the `isDeviceAllowed` identity.
- Clear the selection when it leaves scope, so a server or workspace switch cannot leave a stale
  device selected.
- Re-fetch `/keys` on a server switch. `buildServerUrl` reads the selection from `localStorage` at
  call time, so without `selectedServer` in the effect's deps nothing retriggered the fetch and the
  detail rows stayed those of the previous server.

The scope-clearing effect is gated on a **non-empty raw host list**, not on `isLoading`:
`HostManagerProvider` copies the server payload into `availableHosts` from an effect, and a child
component's effects run before its provider's, so on the commit where loading flips false the list
is still empty for one render. An `isLoading` gate would have cleared the `?device_name=` deep link
on every cold load.

## Verification

`tests/frontend/DeviceInfoOverrides.test.tsx` — 6 tests, 3 of them new (workspace filtering,
workspace-scope clearing, server-absence clearing). All 6 pass with the fix; the 3 new ones fail
against the previous page. `eslint --max-warnings 0` and `tsc --noEmit` clean.

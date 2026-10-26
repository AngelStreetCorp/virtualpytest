# BUG-0524 — Device Info page opens with an empty dropdown

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0524                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On `https://virtualpytest.angelstreet.io/device-info` (no `?device_name=&host_name=`
deep link), the page renders a single empty "Device" dropdown with no selection and
no hint of what to do next. The Device / Gateway tabs and the override table only
appear once a device is picked — so a first-time visitor sees a half-page of nothing
and has to open the dropdown manually.

Reproduces any time the host manager has at least one device with `device_info` or
`gateway_info` keys. With no devices at all the empty state message ("No devices
with info") is correct and still shows up — that branch is not affected.

## Root cause

`DeviceInfoOverrides.tsx` initialised `selected` from the deep-link search params and
left it `''` when none was supplied. The host list loads asynchronously, so on the
first commit `devices` is `[]` and `selected` is `''` — a real, valid empty state
("nothing to choose yet, waiting for the host manager"). Once `devices` populated,
nothing filled the selection. The user had to open the dropdown and click to land on
the actual content.

## Fix

`frontend/src/pages/DeviceInfoOverrides.tsx` — added a `useEffect` that auto-selects
the first device once the host list has loaded and `selected` is still empty. Uses the
same alphabetical/favorites order the `<Select>` renders (favorites first, then
`devices[0]`), so the highlighted row matches the one the user would see if they
opened the dropdown.

Two cases are deliberately left empty: (1) no host has any info keys — the existing
"No devices with info" `<MenuItem>` still renders; (2) a deep link was provided but
its target is now out of scope (server switch, workspace change) — the existing
drop-scope effect clears `selected` and the new auto-select effect explicitly bails
out via a `hasInitialDeepLink` flag, so a stale deep link still surfaces as an empty
dropdown rather than silently re-pointing at another device.

`tests/frontend/DeviceInfoOverrides.test.tsx` — added two tests covering the new
behavior (auto-selects on cold load; "No devices with info" still shows when nothing
has keys) and fixed a pre-existing mock gap: `useHostData`'s `getAllHosts` was
missing from the stub, so `DeviceMaintenanceBadge` crashed during render and the
existing four scoping tests failed on a clean tree. The mock now returns `[]` for
`getAllHosts`; the tests on this file now pass (8/8) without any other change.

## Verification

- Vitest on `tests/frontend/DeviceInfoOverrides.test.tsx`: 8 passed (was 1 passed,
  5 failed before the mock fix).
- Manual: open `/device-info` on a server with at least one device — the dropdown
  shows the first alphabetical device (or the first favorite, if any), the Device
  tab and the override table render immediately.
- Manual: deep-link to a device on a server that does not contain it (e.g.
  `?device_name=foo&host_name=bar` while connected to a server whose hosts are
  `baz/qux`) — the dropdown stays empty as before; the auto-select does not fire.
# BUG-0139 — Switching workspace left the old target selected and still under control

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                        |
|-----------|------------------------------------------------------------------------------|
| ID        | BUG-0139                                                                     |
| Reported  | 2026-09-17                                                                   |
| Status    | Fixed (pending deploy)                                                       |
| Severity  | Medium (a lock held on a device the workspace excludes; a Run could still use it) |
| Area      | `frontend/src/contexts/HostManagerProvider.tsx`, `useDeviceControl`, `useTargetSelection` |
| Fixed in  | Unreleased                                                                   |
| Commit    | `812eb51bc5`                                                                 |

---

## Symptom

On QuickTest, with control taken on `samsung SM-G998B (host-clone-1)`, switching the navbar's
**Workspace** to one whose device filter does not contain that device changed nothing in the
header: the Target field still named the device, the green **Release** button still sat there,
and the device stayed locked server-side.

The device was gone from the dropdown at the same time — so the picker offered a list the
selection was not in. Pressing **Run** would have executed on a device the active workspace
excludes.

## Root cause

Workspace scoping had been applied to the *lists* and nowhere else.

`useQuickTestBuilder` filters `availableHosts` through `isDeviceAllowed`, and
`useTargetSelection` filters `getDevicesFromHost`/`allHosts` the same way. But the *selected*
target for every single-target page — QuickTest, NavigationEditor, TestCaseBuilder, device
control — is not local to those hooks. It lives in `HostManagerProvider` as `selectedHost` /
`selectedDeviceId` / `isControlActive`, and nothing there had ever heard of a workspace. A
switch changed `isDeviceAllowed`, every list re-filtered, and the three fields the header
actually renders kept their old values.

The lock is the part that matters beyond cosmetics: `releaseControl` is only ever called from a
button, so control stayed held on hardware the user could no longer see — and the session that
held it had no UI left to release it with.

RunTests was not affected by the live switch; `useTargetSelection` already prunes a selection
that stops being allowed. Its hole was narrower: the mount-time restore in `RunTests.tsx` replays
`selectedTargetKeys` out of `sessionStorage` through `toggleTarget`, keys that may have been
saved under a different workspace. The prune effect keys off `isDeviceAllowed` changing, so if
the workspace was already resolved when the restore ran, nothing re-checked those keys.

## Fix

- `HostManagerProvider` — one effect: when the active workspace stops allowing the selected
  device, release its lock (if this session could be holding it) and clear the selection and the
  remote/AV panels. One place covers every page that takes a single target, because they all read
  the selection from here.
- The navigation-editor rehydrate effect skips a device the workspace disallows, because the
  release above is async and `activeLocks` / `remoteLocks` still name the device for a tick — the
  rehydrate would otherwise put it straight back.
- `useDeviceControl` — a null `host` now means "not in control". The hook's `isControlActive` was
  only ever synced inside `if (host)`, so a consumer reading the hook's own flag (rather than the
  provider's) kept rendering **Release** after the selection was cleared. The captured cleanup
  params are left alone, so the unmount release still fires; the server no-ops a release the
  session does not own (`not_lock_owner` → `success: true, released: false`).
- `useTargetSelection.toggleTarget` — refuses a device the active workspace disallows, which
  closes the RunTests restore path and any other route into the selection.

## Verification

Type-check (`tsc --noEmit`) and lint are clean. The behaviour itself has **not** been exercised in
a browser: `virtualpytest.angelstreet.io` was answering 502 while this was written, and the change
is in a built bundle, so confirming it needs a deploy.

To confirm once deployed:

1. Open `/builder/quick-test`, pick a target, take control — **Release** turns green.
2. Switch **Workspace** to one whose device filter excludes that device.
3. Expect: Target clears, the remote/AV panels close, the button returns to **Take Control**, and
   `GET /server/control/lockedDevices` (or the device's lock badge) no longer shows the manual lock.
4. On `/run/tests`, select a target, switch workspace, reload the page: the restored selection
   must not bring the excluded device back.

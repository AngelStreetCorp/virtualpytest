# BUG-0753 — Apple TV IR remote: button boxes bunched in the top-left corner on older builds

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0753                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On a client install built before 2026-10-06, Take Control of an Apple TV driven by an IR remote
(here an IRTrans box) shows the Magenta TV remote picture, but the clickable button boxes sit in
a cluster in its top-left corner. Clicking a visible button sends nothing: the host journal has
no `Sending …` line from the remote controller, while the status dot stays green.

## Root cause

`frontend/src/config/remote/appleTvRemote.ts` on those builds still has the button positions of
the earlier picture (x 50–150, y 50–450). The Magenta TV picture was already in
`frontend/public/appletv_remote.png`; the layout matching it landed in 27cc0ab34 and 6eeccc68c.
`InfraredRemote.tsx` places each box at `position × remoteScale`, so the old positions land in
the corner. The green dot only reports that the IRTrans box is reachable, not that a key was sent.

## Fix

No code change on main. Client patch **patch-4** (`patch/patch_frontend_4_appletv-remote-layout.sh`)
puts the current `appleTvRemote.ts` on the install and restarts `vpt-frontend-prod`, whose
`ExecStartPre` rebuilds the bundle.

## Client patch

- Number: patch-4, script `patch/patch_frontend_4_appletv-remote-layout.sh`.
- Run on the frontend machine (the one with `vpt-frontend-prod`), not on a host:
  `bash patch_frontend_4_appletv-remote-layout.sh --check && sudo bash patch_frontend_4_appletv-remote-layout.sh`
- Verify: the script checks that `frontend/dist` carries the new layout; then reload Take Control
  (hard refresh) and click OK: the host journal shows `Sending OK -> 'sndccf …'`.
- Undo: `sudo bash patch_frontend_4_appletv-remote-layout.sh --rollback`.

## Verification

Tested on a copy of the old file (`VPT_FRONTEND_UNIT=none`): `--check` says needed (10), apply
writes the main file, a second `--check` and apply say already applied, `--rollback` restores the
old file and a second rollback says nothing to restore. The `verify` pattern `x:397,y:50` matches the
lab frontend bundle.

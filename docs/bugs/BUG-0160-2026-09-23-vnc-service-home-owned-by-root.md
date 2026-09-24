# BUG-0160 — VNC service could not create its X11 authority file

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0160                                                     |
| Reported  | 2026-09-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host, Linux VNC                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | `TBD`                                                        |

---

## Symptom

On a Linux host where `/var/lib/vpt_user` was owned by root, `vpt-vnc.service` repeatedly
restarted. TigerVNC logged `xauth: timeout in locking authority file
/var/lib/vpt_user/.Xauthority`; no persistent X server or `.Xauthority` file was left behind.

## Root cause

The service runs as `vpt_user`, but the home directory could be created or left owned by root.
TigerVNC's `xauth` could not create its authority file in that directory, so the VNC session
failed to initialize. The unit did not repair the home and XDG data directory ownership before
starting TigerVNC.

## Fix

`backend_host/config/services/linux/vnc.service` now runs a privileged `install -d` pre-start
step to ensure `/var/lib/vpt_user`, `.cache`, and `.local/share` exist and are owned by
`vpt_user` before the service launches TigerVNC.

## Verification

Install or regenerate the unit on a Linux host, set `/var/lib/vpt_user` to root ownership to
simulate the failure, then restart `vpt-vnc.service`. The pre-start step should restore the
home directory ownership, TigerVNC should create `/var/lib/vpt_user/.Xauthority`, and the unit
should remain active with a listener on port 5901.

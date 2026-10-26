# BUG-0823 — vpt-stream does not start after a reboot on hosts with screencap loops

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0823                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | setup / systemd units (backend_host)                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

After a reboot of vpt-mf1 every device tile showed "Loading stream..." and no ffmpeg capture ran:
`vpt-stream.service` was `enabled` but `inactive (dead)`. A manual `systemctl start vpt-stream` fixed it.

## Root cause

`emulator-fifo@.service` had `After=multi-user.target` and `Before=vpt-stream.service`, and both units are
`WantedBy=multi-user.target`. That is an ordering cycle (multi-user.target → vpt-stream → after emulator-fifo →
after multi-user.target). The boot journal shows `Job vpt-stream.service/start deleted to break ordering cycle`:
systemd drops one start job and vpt-stream silently never starts. Only hosts with `vpt-emulator-fifo@deviceN`
instances (vpt-mf1: device6, device7) are affected.

## Fix

Removed `After=multi-user.target` from `backend_host/config/services/linux/emulator-fifo@.service`
(`Before=vpt-stream.service` alone gives the order the unit needs). Installed hosts need the unit re-copied and
`systemctl daemon-reload`.

## Verification

`journalctl -b | grep "ordering cycle"` is empty after a reboot and `systemctl is-active vpt-stream` is `active`.

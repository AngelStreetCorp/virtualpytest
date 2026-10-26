# BUG-0602 — vpt-windows `Host_Windows` tile pure black (TightVNC screen-hook capture)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0602                                                     |
| Reported  | 2026-10-17                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / Windows VNC                                   |
| Fixed in  | build 90145 |
| Commit    | `shortHash` (or "TBD")                                       |

---

## Symptom

The `Host_Windows` tile (host name `vpt-windows` on `/device-control`, server
`vpt-pi4`) rendered a pure black noVNC canvas. The iframe loaded
(`/host/vpt-windows/vnc_lite.html` → 200), noVNC reported
`Connected to desktop-uni4mdl`, tvnserver's Application log said
`Authentication passed by <ip>` — and the framebuffer was a single colour,
`#000000`, at 1920×1200.

## Root cause

The desktop was healthy; TightVNC's capture was not.

- A screenshot taken **inside** the interactive session (a one-shot Scheduled
  Task running as `joach` in session 1, GDI `CopyFromScreen`) returned
  `1920×1200`, mean RGB `(59, 96, 84)`, 281 699 unique colours.
- A direct RFB capture of the server (loopback, `vncdotool` probe) returned the
  same `1920×1200` geometry with mean RGB `(0,0,0)` and **one** unique colour.
- During a live client, `netstat -ano` showed port 5900 `ESTABLISHED` owned by
  the session-0 `tvnserver.exe -service` process, not by the session-1
  `tvnserver.exe -controlservice -slave` — i.e. Session 0's empty desktop was
  being served.
- TightVNC 2.8.90 captures through `screenhooks64.dll` + `hookldr.exe` (no
  mirror driver: `dfmirage` absent). On this Windows 11 + AMD Radeon RX 5700 XT
  desktop the hook path produces all-black frames while GDI capture works.

## Fix

Registry `HKLM\SOFTWARE\TightVNC\Server` (and `WOW6432Node` when it exists):

```
UseMirrorDriver      = 0
UseHooks             = 0    ; do not use screen hooks
PollFullScreen       = 1    ; GDI full-screen polling
AllowLoopback        = 1    ; websockify connects from 127.0.0.1
RfbPort              = 5900
AcceptRfbConnections = 1
```

Then stop/start the native service (`Stop-Service tvnserver -Force;
Start-Service tvnserver`) so it re-spawns its session-1 slave with the new
config. `setup/local/windows/backend_host/install_host_windows.ps1`
(`Setup-VNC`) now writes the three capture values, so a reinstall keeps the fix.

Notes for the next person:

- The loopback value is `AllowLoopback` (the binary's strings contain
  `AllowLoopback` / `LoopbackOnly`); `AllowLoopbackConnections` is not read.
- Starting a slave by hand in session 1 does **not** make the service hand off
  the connection; the service kept serving Session 0.
- Application mode (`tvnserver.exe -run` in session 1) refuses loopback clients
  (`Sorry, loopback connections are not enabled`), which is exactly what
  websockify uses — not a drop-in replacement.

## Verification

- Direct RFB capture on the host after the change: `1920×1200`, mean RGB
  `(167, 169, 139)`, 194 231 unique colours.
- Headless browser on `/device-control?auto_signed=…` (server `vpt-pi4`): the
  `vpt-windows` card mounts its noVNC iframe after hover (`vnc_lite.html` 200),
  and the tile screenshot shows the live desktop (`Connected to
  desktop-uni4mdl`).

## Not covered

`/device-control`'s legacy 1440×847 CSS transform still crops a 1920×1200
framebuffer (BUG-0590 covers the REC tile / Take Control fix); the desktop is
live but the viewport scaling fix has not been applied to that page.

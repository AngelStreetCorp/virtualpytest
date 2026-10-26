# BUG-0464 — Host screenshot and archive dead on vpt-mf1: x11grab has no X cookie

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0464                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host, Linux capture (`run_ffmpeg.sh`)                |
| Host      | vpt-mf1                                                     |
| Fixed in  | build 90145 |
| Commit    | _pending_                                                    |

## Symptom

On `vpt-mf1` the **host** device (`vpt-mf1-host`, `HOST_VIDEO_SOURCE=:1`) produced no picture and
no archive. In the browser the device page logged

```
<pi-server-host>/server/av/takeScreenshot?team_id=…  →  500
```

and the capture directory for the host stayed completely empty:

```
/var/www/html/stream/capture/hot/{captures,thumbnails,segments,metadata}   →  0 files
```

while the USB grabbers (`capture1/2/3/5/6/7`) were perfectly healthy and archiving normally.

`vpt-archiver.service` and `vpt-monitor.service` were both **running** and both **correct** — the
monitor's `freeze` verdict on every capture was an accurate report of a dead host capture, not a
fault in the monitor itself. The archiver's `1min MP4 not created` and `Segments available: 0` for
`capture` were likewise accurate.

## Cause

The host capture is the only one that grabs the VNC desktop over X11 (`x11grab -i :1`). Its
ffmpeg died immediately on every start:

```
Authorization required, but no authorization protocol specified
[x11grab @ …] Cannot open display :1, error 1.
Error opening input file :1.
```

The two services run as the **same user** but with **two different homes**:

- `vpt-vnc.service` sets `Environment=HOME=/var/lib/vpt_user`, so TigerVNC created the display's
  MIT-MAGIC-COOKIE-1 in **`/var/lib/vpt_user/.Xauthority`**.
- `vpt-stream.service` runs `run_ffmpeg.sh` as `User=vpt_user` **without** overriding `HOME`, so
  systemd gave it **`/home/vpt_user`** — a directory with no `.Xauthority` in it at all.

With `XAUTHORITY` empty, Xlib falls back to `$HOME/.Xauthority`, finds nothing, and refuses the
connection. The watchdog then did the right thing with the wrong information: ffmpeg wrote its
error to the log once and exited, the 61 s staleness check fired, and it restarted the capture every
60 s forever — which is why the host stream looked alive in `active_captures.conf` while producing
nothing at all.

`run_ffmpeg.sh` also commented *"X11 access is configured by vncserver.service ExecStartPost"*, but
no such step exists — in the repo unit or the deployed one. The access was assumed and never
provided.

A second, quieter symptom rode along: `get_vnc_resolution()` calls `xdpyinfo`, which needs the same
cookie. It failed, returned empty, and silently degraded to the `1280x720` fallback.

## Fix

`run_ffmpeg.sh` now resolves the X cookie itself before anything touches the display, via a new
`setup_x11_auth()` helper. It prefers an already-exported readable `XAUTHORITY`, then asks the live
X server for its own `-auth` path (`pgrep -a -f Xtigervnc …` / `Xorg` / `Xvfb`), then falls back to
the VNC home and `$HOME`. Asking the X server is authoritative, so the fix survives a change of VNC
home instead of hard-coding one path.

The call sits immediately before `export DISPLAY="$source"`, which means `get_vnc_resolution()`'s
`xdpyinfo` is covered too.

## Verification

On `vpt-mf1`, running the helper as `vpt_user`:

```
HOME=/home/vpt_user
🔐 X11 auth: XAUTHORITY=/var/lib/vpt_user/.Xauthority
```

- Without the cookie, `ffmpeg -f x11grab -i :1` → `Authorization required…`, no file written.
- With the resolved cookie, the same command writes a valid 1280×720 JPEG — the live XFCE
  desktop, clock reading `2026-10-11 21:32`.

`bash -n` passes. Restart `vpt-stream` after deploying for the host capture, its archive, and the
`takeScreenshot` endpoint to recover.

## Not involved

- `vpt-archiver.service` — running, healthy, correctly reaping to its limits.
- `vpt-monitor.service` — running, healthy; its `freeze` call was accurate.
- `vpt-vnc.service` — running 3 days, display `:1` and its cookie intact.
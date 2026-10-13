# BUG-0220 — A device's frames went unanalysed for days when the capture monitor started before its grabber was listed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0220                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / capture monitor                               |
| Fixed in  | Unreleased                                                   |
| Commit    | `this commit`                                                |

---

## Symptom

The Fleet Health dashboard reported `vpt-pi4 / host` (the host's own desktop, model
`host_vnc`) **DOWN — capture stalled, latest frame 37h old**, while the same host's camera was
fine, its badge in the app was `online` and its VNC tile showed the desktop live.

Nothing else noticed:

- ffmpeg was healthy and still writing desktop frames at 10 fps into `capture/hot/captures/`.
- No freeze / blackscreen / audio incident was ever raised for that device — the component that
  raises them was the one not looking.
- The newest metadata JSON kept a fresh file mtime, because the audio check rewrites it; only its
  `timestamp` field was frozen.

## Root cause

A startup race between `vpt-stream` and `vpt-monitor` on a cascaded restart (all `vpt-*`
services restarted within seconds, 2026-09-29 22:54 UTC):

1. `run_ffmpeg.sh` deletes `active_captures.conf` and appends one line per grabber as each
   ffmpeg starts — `capture1` (camera) first, `capture` (desktop) last, at 22:54:12.5.
2. `capture_monitor.py` `main()` read the list once, at 22:54:12, while it still held only
   `capture1`, and built its inotify watches from that.
3. Nothing ever read it again. `capture/hot/captures` never had a watch, so not one desktop frame
   was analysed until the monitor was restarted.

None of the safety nets cover this: the ffmpeg watchdog checks ffmpeg (healthy), the monitor's
stall watcher only sweeps devices it already watches, and systemd sees the unit running. The same
race can drop any device on any host. The `host` device's "No JSON analysis files found" on
2026-09-23/24 was probably the same thing (those logs have rotated away).

## Fix

`backend_host/scripts/capture_monitor.py`: the monitor re-reads `active_captures.conf` every
10 s (`_maybe_rescan_capture_dirs`) and registers any capture dir it does not know yet — watch,
frame worker and incident worker, the same path as at startup (`_register_capture_dir`). A dir
listed before it exists on disk is retried on each rescan instead of being given up on. Dirs are
only added, never removed. The inotify loop now yields a tick every idle second
(`event_gen(yield_nones=True)`) so the rescan also runs on a host whose only devices were the
ones missed.

Immediate remediation on vpt-pi4 (before the fix shipped): `systemctl restart vpt-monitor` only —
the conf was already complete. Restarting `vpt-stream` as well would rewrite the conf and could
lose the race again.

## Verification

- Harness (macOS watchdog path, real temp dirs): monitor starts with only `capture1` listed;
  `capture2` is appended afterwards and `capture3` is listed before its dir exists. Within one
  rescan both are watched, and a frame written into each of the three is queued to its own worker.
- On vpt-pi4's venv: `inotify.adapters.Inotify.event_gen(yield_nones=True)` yields `None` after
  1 s idle, and a watch added while the generator is running receives `IN_MOVED_TO`.
- After deploy, on a host: `journalctl -u vpt-monitor | grep "added after startup"` shows any dir
  picked up late; every grabber in `active_captures.conf` has fresh `capture_*.json` in its
  `hot/metadata`; the Fleet Health **Live** row shows no "capture stalled" for a device whose
  ffmpeg is running.

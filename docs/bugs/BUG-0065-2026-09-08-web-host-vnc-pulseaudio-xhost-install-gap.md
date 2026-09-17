# BUG-0065 — Web-test VNC host installer never wired audio, missing `xhost +local:`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0065                                                     |
| Reported  | 2026-09-08                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                        |
| Area      | infra / install script / stream                              |
| Fixed in  | build 8713                                                   |
| Commit    | this commit                                                  |

---

## Symptom

On `sample-app-web` (a `host_vnc` web-testing host), the desktop session's PulseAudio had
been dead for 12+ hours with no automatic recovery — the xfce4-panel audio plugin
logged "Disconnected from the PulseAudio server. Attempting to reconnect in 5
seconds..." continuously (2.5M+ lines). `HOST_VIDEO_AUDIO=null` was set on this host,
so the stream's ffmpeg pipeline never captured audio at all — no error, just silently
video-only, matching a config someone had set deliberately rather than a live crash
being visible anywhere.

Once `HOST_VIDEO_AUDIO` was flipped to `default` to match the working reference host
(`host-clone-1`), the stream destabilized further: ffmpeg entered a ~60s restart loop,
then failed outright with `Authorization required, but no authorization protocol
specified` / `Cannot open display :1`.

## Root cause

Two separate, compounding gaps, both present in `install_host.sh`'s installer output
(so any newly-provisioned or re-installed host would reproduce this):

1. **No pulse self-heal without audio enabled.** `run_ffmpeg.sh` already restarts
   PulseAudio (`pulseaudio --start --exit-idle-time=-1`) whenever `pactl info` fails —
   but only inside the `HOST_VIDEO_AUDIO=default|pulse` branch. `allow-exit=no` in
   `/etc/pulse/daemon.conf` (present on both hosts already) only prevents *graceful
   idle-exit*, not a crash. With audio disabled, a crashed pulse daemon had zero path
   back to life — not even a symptom outside the VNC desktop's own audio icon.
2. **`install_host.sh`'s xstartup template never called `xhost +local:`.** Without it,
   every new x11grab (ffmpeg) process depends entirely on presenting a matching
   `.Xauthority` cookie to connect to display `:1`. `host-clone-1` only had this
   because someone patched its deployed `xstartup` by hand at some earlier point — the
   installer itself never wrote it, so `sample-app-web` (and any other host installed since)
   never got it. This is what surfaced as the X11 `Authorization required` failure
   once the stream was restarted enough times while iterating on the audio fix.

Confirmed via a live reboot of `host-clone-1`: it came back clean specifically because
its already-deployed (but not installer-sourced) `daemon.conf`/`xstartup` patches
persisted across reboot — not because the installer or `run_ffmpeg.sh` alone would
have produced that state on a fresh host.

## Fix

- `setup/local/linux/backend_host/install_host.sh`: xstartup heredoc now writes
  `xhost +local: 2>/dev/null || true` right after `export HOME=...`, so every new
  install gets local X access parity with `host-clone-1` from day one.
- `docs/agent/devices/STREAM.md`: documented the `allow-exit` vs. exit-idle-time vs.
  crash distinction, that the self-heal only runs when audio is enabled, the concrete
  recovery recipe (`restart vpt-vnc` → `restart vpt-stream`), and the `xhost +local:` /
  X11 auth gotcha with its fix and verification (`DISPLAY=:1 xhost` should list
  `LOCAL:`).
- On `sample-app-web` itself (already applied live, not part of this commit): pulse
  restarted, `HOST_VIDEO_AUDIO=default`, `xhost +local:` added to its deployed
  `xstartup`, `vpt-vnc`/`vpt-stream` restarted — confirmed stable (ffmpeg running with
  `-f pulse -i default`, no restart loop, frames incrementing continuously).

## Verification

- `sample-app-web`: `ps -u vpt_user -o cmd | grep pulse` shows a live `pulseaudio --start
  --exit-idle-time=-1` process bound to `:4713`; `ps auxww | grep ffmpeg` shows
  `-f pulse -thread_queue_size 2048 -i default ... -c:a aac`; `DISPLAY=:1 xhost` (as
  `vpt_user`) lists `LOCAL:`; `vpt-stream` journal shows no "Stale ffmpeg" restarts
  over several minutes.
- For a **new** host: run `install_host.sh`, then on the deployed box check
  `grep xhost /var/lib/vpt_user/.vnc/xstartup` returns the new line.

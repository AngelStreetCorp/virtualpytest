# BUG-0101 — A capture whose input stalls is invisible to the watchdog: no segments for 67h, log "healthy"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0101                                                                    |
| Reported  | 2026-09-15 (`vpt-pi1` / `S21x`, found while investigating a missing stream on QualiAI) |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High (a device silently has no stream until a human notices and restarts the service; every verification against it is then blind) |
| Area      | `backend_host/scripts/run_ffmpeg.sh` — `check_grabber_health()`              |
| Fixed in  | build 9151                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

`S21x` (`vpt-pi1`, `device1`) showed "No stream" everywhere — VPT and QualiAI alike. The public
manifest 404'd:

```
GET https://rpitest.angelstreet.io/host/vpt-pi1/stream/capture1/segments/output.m3u8   404
GET https://rpitest.angelstreet.io/host/vpt-pi1/stream/capture2/segments/output.m3u8   200
```

On the Pi, `capture1` had no `hot/segments/output.m3u8` at all while `capture2/3/4` had fresh ones.
Its grabber was **running and logging**:

```
frame=2441384 fps=9.5 q=33.0 size=N/A time=67:48:58.40 bitrate=N/A dup=1 drop=0 speed=0.947x
frame=2441384 fps=9.5 q=33.0 size=N/A time=67:48:58.40 bitrate=N/A dup=1 drop=0 speed=0.947x
…                                            ← log mtime current, frame number frozen
```

The same line, at the same frame, for about 67 hours. `journalctl -u vpt-stream` shows the
watchdog restarting `device3` twice that morning and **never once touching `device1`**.

## Cause

`check_grabber_health()` had two liveness signals, and a stalled *input* defeats both:

| signal | what it measures | why it missed this |
|---|---|---|
| `age > STALE_SEC` | mtime of `/tmp/ffmpeg_output_<id>.log` | ffmpeg keeps printing its progress line every second, so the log mtime is always current |
| `size_mb ≥ LOG_RUNAWAY_MB` | log size, for a per-frame error flood | a frozen progress line repeats slowly; the log never approaches 100 MB |

The runaway guard's own comment states the first hazard ("a spewing ffmpeg writes constantly, so
its log mtime stays fresh") — the mirror case was simply never covered. Both signals watch the
*process*; neither watches whether anything comes **out** of it.

## Fix

A third detector that measures the output: if the newest `.ts` in the grabber's segments directory
(`<capture_dir>/hot/segments`, or `<capture_dir>/segments` when RAM mode is off) is older than
`OUTPUT_STALL_SEC` (60 s — segments are sub-second), the grabber is restarted. A capture that
produces nothing is down however healthy the process looks. Grabbers that have never written a
segment are skipped, so a source with no HLS pipeline is never touched.

The rate limit, the dormant cap and the flap back-off are now in one
`restart_unhealthy_grabber()` helper shared by all three detectors, instead of being copy-pasted
per detector — so a policy fix can no longer land in one branch and miss the others. Each detector
passes its own reason string, which is what the log message reports.

## Note

The capture recovered at 18:47 that day via a manual `systemctl restart vpt-stream`, not on its
own — which is exactly the gap: recovery required a human. With this detector it would have
restarted itself within a minute of stalling.

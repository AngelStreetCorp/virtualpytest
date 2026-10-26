# BUG-0745 — Dashboard auto-fix cannot fix a dead x11grab device: the restart keeps hitting the same broken X cookie

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0745                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | backend_host, Linux capture (`run_ffmpeg.sh`)                |
| Host      | any `host_vnc` host capturing an `:N` display                |
| Fixed in  | build 90145 |
| Commit    | _pending_                                                    |
| Related   | [BUG-0464](../bugs/BUG-0464-2026-10-11-host-x11grab-xauthority-missing.md) |

## Symptom

The dashboard shows `vpt-stream` down (or a stopped host device with no ffmpeg behind it).
Pressing **auto-fix** reports that it restarted the service — and nothing changes. The device
stays dead, and `/tmp/ffmpeg_output_host.log` keeps saying:

```
Authorization required, but no authorization protocol specified

[x11grab @ 0x5602dcd378c0] Cannot open display :1, error 1.
[in#0 @ 0x5602dcd37780] Error opening input: Input/output error
Error opening input file :1.
```

An operator watching this cycles: auto-fix → same error → auto-fix. Only an SSH session can
end it.

## Cause

BUG-0464 taught `run_ffmpeg.sh` to *find* an X cookie (`setup_x11_auth`) but nothing ever
verified that the cookie worked, and nothing repaired it when it did not. Two distinct states
both end in the same log line and neither can be fixed by restarting the consumer:

1. **No cookie to find.** `vpt-stream` runs with a different `HOME` than `vpt-vnc`, so the
   fallback list misses and ffmpeg is launched with an empty `XAUTHORITY` (BUG-0464's shape).
2. **A cookie that no longer matches.** The X server rotated or regenerated its cookie and
   never rewrote the file the grabber reads. Any amount of restarting reproduces the failure.

Auto-fix is a *restart* by design — `controlService` allowlists units and calls
`sudo systemctl restart`. It has no notion of a fault that survives a restart. So for an
x11grab device the button was structurally incapable of fixing what it was being asked to fix:
each press re-ran the same failing launch, and the staleness watchdog's own 60 s retry loop
(`STALE_SEC` / `RESTART_SPACING_SEC`) produced exactly the same error on the same schedule,
which is why the host looked busy rather than broken.

## Fix

Two changes, both in `run_ffmpeg.sh`, deliberately placed so that **every** entry point heals —
the dashboard's restart, a systemd restart, the watchdog, and a source switch alike.

**1. Every x11grab start verifies the display and repairs it.**
The x11grab branch of `start_grabber` now asks `xdpyinfo` whether the display is actually
readable *after* the cookie is resolved, and if it is not, calls `repair_x11_auth` before
building the ffmpeg command. `setup_x11_auth` only finds a cookie that already exists on disk;
this is the step that handles a cookie that exists and does not work — which is precisely what
auto-fix could not do.

**2. The stall watchdog recognises the fault and repairs it before restarting.**
`x11_auth_fault` matches the log signature (`Authorization required…` / `No protocol specified`)
on a *quiet* log, and `restart_unhealthy_grabber` calls `repair_x11_auth` **before** killing and
restarting the grabber. Repairing first means the restart lands on a working cookie instead of
reproducing the failure and burning a retry plus a minute of wall clock. On a successful repair
the device's failure counter resets, so a device that recovered on cookie repair is not walked
into the dormant state by the faults that preceded the repair.

**`repair_x11_auth` escalates cheapest-first and proves itself:**

| Step     | Action                                    | Fixes                                   |
|----------|-------------------------------------------|-----------------------------------------|
| *precheck* | `xdpyinfo` already reads it → return 0    | healthy displays cost one probe, change nothing |
| `resolve`  | `setup_x11_auth` (X server's `-auth`, then VNC home, then `$HOME`) | no/misspelled cookie (BUG-0464) |
| `grant`    | `xhost +local:` — same-host connections bypass cookie matching | rotated cookie; also a host whose `xstartup` never ran the grant |
| `regrant`  | re-resolve the cookie once                | the grant changed what the server accepts |
| *final*    | one-frame `ffmpeg -f x11grab` must write a real file | the only verification that matches what ffmpeg does |

Two deliberate boundaries:

- **It never escalates past the grant.** Restarting `vpt-vnc` regenerates the cookie from
  scratch, but it drops any live VNC session — an operator's or a running test's. That stays
  the dashboard's/operator's call, not a 30 s watchdog's.
- **It reports failure honestly.** If the probe still fails it returns 1 and says it is falling
  back, so the caller reverts to the normal restart/dormant policy rather than looping on a
  repair that does not work. It only claims success after verifying.

The detection is deliberately narrow: only a `x11grab` source, only the fault signature, only on
a log that has gone quiet. A log that *once* showed the fault while a capture is running fine
must not be repaired again, and an ordinary output-stall log (no auth line) must keep going to
the existing restart/dormant path untouched.

## Verification

`bash -n backend_host/scripts/run_ffmpeg.sh` passes.

`tests/backend_host/test_x11_auth_autofix.py` — 16 tests, all passing. The three helpers are
sliced out of the real `run_ffmpeg.sh` (so editing the logic breaks the test) and driven against
fakes for `xdpyinfo`, `xhost`, `ffmpeg`, `pgrep` and `stat`. No X server, no display, no real
cookie, no real ffmpeg. Covered:

- a healthy display is left **completely** untouched — no `xhost` grant, no ffmpeg probe, no
  repair claimed (the watchdog must not mutate healthy hosts every 30 s);
- the `xhost +local:` escalation fires and is actually issued;
- the last-resort one-frame probe runs and targets the right display;
- an unrepairable display returns 1, announces the fallback, never claims success, and leaves no
  temp file behind;
- the exact reported log is recognised, while a fresh log, a stalled-but-healthy log, a missing
  log, and a fault buried under 60 lines of fresh progress are all correctly **not** faults;
- the watchdog calls `repair_x11_auth` *before* `kill_all_ffmpeg_for_device`, gated on both the
  fault signature and an x11grab source.

Deploy and `sudo systemctl restart vpt-stream`.

## Notes found while fixing this

**BSD `mktemp` does not substitute trailing X's.** The frame probe originally used
`mktemp /tmp/vpt_x11_probe_XXXXXX.jpg`. On macOS that returns the template *verbatim* — every run
would write the same predictable `/tmp` path, colliding between devices and re-introducing a
symlink-attack surface. The probe now runs inside a `mktemp -d` directory, with the `.jpg`
suffix on the file inside it (ffmpeg needs the extension to pick an encoder).

## Not involved

- **The dashboard's auto-fix button** — correct as written; it restarts services. The bug was
  that a restart could not fix *this* fault, which is why the repair now lives where every
  restart passes through it.
- **`vpt-monitor-img` / `vpt-archiver`** — both correctly reported a dead capture, as they did
  in BUG-0464.
## Client patch

**patch-1** — `patch/patch_host_1_x11-xauthority.sh`, for a host that has not taken the update yet.
Apply on the host: `sudo bash patch_host_1_x11-xauthority.sh --check` (exit 10 = needed), then `sudo bash patch_host_1_x11-xauthority.sh`.
It grants only the service user on the display (`xhost +SI:localuser:vpt_user`), adds that line to the VNC
`xstartup` (backup `xstartup.patch-1.bak`) so it survives a VNC restart, restarts `vpt-stream` and proves a real one-frame
grab. It never restarts `vpt-vnc`. Verify: the ffmpeg log no longer shows "Authorization required" and the dashboard shows the stream up.

### Lab test (2026-10-21, `host-clone-1`, Xtigervnc :1 as vpt_user, old `run_ffmpeg.sh`, lease released afterwards)

| Step | Result |
|------|--------|
| Break: removed the `+local:` and `localuser:vpt_user` grants, emptied the cookie, restarted `vpt-stream` | ffmpeg log shows `Authorization required, but no authorization protocol specified` / `Cannot open display :1, error 1` (the client's symptom) |
| `--check` | `needed ...`, **exit 10** |
| Cookie file present but not found by the service user's HOME (the client's state), apply | first run failed at the frame check: **bug found** - the probe directory was root-owned `0700`, so `vpt_user` could not write `probe.jpg` (the display itself opened fine). Same output as the client run |
| Fix: the probe directory is chowned to the service user | apply: grant, xstartup line (backup), `vpt-stream` restart, `done: ... a real frame was grabbed`, **exit 0**; ffmpeg log has 0 auth errors, 4 new `capture_*.jpg` in the last minute |
| Second `--check` and second run | `already applied`, exit 0, `xstartup` md5 unchanged, `vpt-stream` not restarted |
| Not covered | an emptied cookie (no usable cookie): the patch refuses with "xhost grant refused ... Not changed" and asks for a `vpt-vnc` restart, by design |

The host was put back as found (grants `+local:` and `localuser:vpt_user`, original `xstartup` and cookie, stream active, 0 auth errors).

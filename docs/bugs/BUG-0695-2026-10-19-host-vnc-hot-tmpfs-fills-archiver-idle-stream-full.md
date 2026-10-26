# BUG-0695 — Screenshots failed on web hosts 30 minutes after a restart: the archiver idled while the stream did not prune

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0695                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host stream / monitor profiles                       |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

During TASK-135 round 1 on host-clone-2 (2026-10-19, after the 16:00 deploy), every `save_node_screenshot` failed with
"Screenshot capture failed: Failed to save screenshot" (12 calls). The host log said `[VNC]: No recent files within 3s. Newest file
age: 56.76s`; `/tmp/ffmpeg_output_host.log` said `No space left on device`; the 200 MB hot tmpfs `/var/www/html/stream/capture/hot` was
100 % full with 3 692 capture frames, and vpt-archiver logged `idle: no device on this host has a profile that needs the archiver service`.

## Root cause

`7eae6efde` gave the host_vnc capture the model default profile `pc` in `shared/src/lib/utils/monitor_profile.py`. `pc` turns the
archiver off and says `stream: lean`, where `run_ffmpeg.sh` prunes the device's captures itself. But `run_ffmpeg.sh`'s own resolver
(`stream_mode_for`) read only `DEVICE<N>_MONITOR_PROFILE` / `MONITOR_PROFILE`, not the model default: it streamed the host_vnc capture
`full`, without pruning. Nothing removed captures, the tmpfs filled about 30 min after the restart, ffmpeg stopped writing frames and
every screenshot (`take_screenshot` wants a frame younger than 3 s) failed. Any host with `HOST_VNC_STREAM_PATH` and no explicit profile
is affected, and so is a phone (`DEVICE<N>_MODEL` android_mobile → `mobile`), whose manifest is not lean, so it only changed name.

## Fix

`backend_host/scripts/run_ffmpeg.sh` `stream_mode_for` applies the same model default as `MODEL_PROFILES` when no profile is set
(host_vnc capture → `pc`, phones → `mobile`). Hosts take it at their next vpt-stream restart.
Unblocked by hand on host-clone-2: kept the newest 150 hot captures (what lean mode keeps) and restarted vpt-stream.

## Verification

`tests/backend_host/test_tv_lite_profile.py::test_run_ffmpeg_applies_the_model_default_like_python` compares the bash and the Python
answer for the model defaults. Live: after the vpt-stream restart on host-clone-2, the hot folder stays at about 150 captures and
`/server/av/saveScreenshot` answers 200.

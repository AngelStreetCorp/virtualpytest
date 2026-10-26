# BUG-0688 — A calm live channel flips from "live" to no badge

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0688 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Medium |
| Area      | backend_host / monitor / localize |
| Fixed in  | build 90145 |
| Commit    | see merge |

## Symptom

stb4 (vpt-pi1/device4) on a live news channel (studio, subtitles) showed `live`, then no badge, then `live` again.

## Evidence

Last frames of capture4 `hot/metadata`: most carry `live` through the motion gate (`gate_skip: live`, a cached verdict). In a calm
studio the motion is a small box or minor (presenter moves, background still), the gate opens, the matcher abstains
(`no qualifying screen (best region 41-88)` or `low-content frame`) and the verdict is `unknown`. That verdict is cached,
so the following motion-gated frames serve `Unknown` for several seconds (gaps of 6-12 s measured). `unknown` renders no badge.

## Fix (smallest of three considered)

`hold_live` in `monitor_localize.py`: an abstain (unknown, or an unnamed known screen) within `LIVE_HOLD_SECONDS` (20 s) of the last real
live reading stays `live`; a node, overlay or signal state still wins at once. Not chosen: a new motion classifier (touches the shared
detector and every channel) and playback / audio cues (not carried in the per-frame localize path).

## Second round (owner: a talking head, audio should have bailed it out)

The monitor's own live window needed a `full` kind; a presenter only gives `minor`. After an abstain the monitor now also counts
slow live (3 ticks of minor/full, each >= 2.0 %, the Localize button's own constants) and audio (frame JSON `audio` + `mean_volume_db` > -50 dB with
motion) as `live`. Thresholds in `FINGERPRINT.md` "Live hold". S21x (vpt-pi1/device1, phone playing a game) had no badge at all:
`DEVICE1_USERINTERFACE` was unset, so Localize is off for it (opt-in per device); set to `clashofclans-android-mobile` in the host
`backend_host/src/.env` (no adb is used by the monitor path). App name from the foreground package is not done: it needs an adb or phone-agent read
that can wedge the agent mid-run.

## Verification

`pytest backend_host/scripts/test_monitor_localize.py -k hold_live`. The matcher (`identify_screen`) is untouched, so the Localize
bench does not move; live behaviour is checked by watching stb4's JSON after deploy.

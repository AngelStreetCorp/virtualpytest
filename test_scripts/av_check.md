# av_check

Is this device actually **playing audio and video**?

`av_check` puts the device on a node that plays sound (a YouTube video on web / mobile,
live TV on an STB, the stream itself on an HLS device), watches it for `--duration`
seconds and gives two verdicts:

| Verdict | PASS when |
|---------|-----------|
| **Video** | the picture is moving (real frame-to-frame motion above `--motion-threshold`) **and** no freeze / black window lasts longer than `--max-freeze-s` |
| **Audio** | sound is present for at least `--audio-min-present` % of the window |

A device that captures no audio at all (VNC / emulator pipeline) gets **Audio: N/A**,
not a failure — the platform cannot measure what it does not capture.

## Usage

```bash
python test_scripts/av_check.py --userinterface example_mobile --node live
python test_scripts/av_check.py --userinterface youtube-web --node video_player --duration 30
python test_scripts/av_check.py --node live --motion-threshold 0.5 --audio-min-present 80
python test_scripts/av_check.py --node live --motion-area "100,200,600,400"
```

It also runs from the **Run** page like `goto.py`: pick the script, the device, the
interface and the node.

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_mobile` | UI interface name |
| `--node` | string | `home` | Node that plays content with sound |
| `--variant` | string | _(empty)_ | Named variant; empty means base data |
| `--duration` | int | `30` | Seconds to watch before judging |
| `--settle-s` | float | `3.0` | Seconds to wait after navigation, before the window starts |
| `--motion-threshold` | float | `1.0` | Minimum frame-to-frame change % that counts as motion |
| `--motion-window-s` | float | `2.0` | Seconds between the two compared frames (capped at 2.0) |
| `--motion-area` | string | _(empty)_ | Optional `x,y,width,height` region, to exclude an animated overlay |
| `--audio-min-present` | float | `60.0` | Minimum % of the window that must carry sound |
| `--audio-level-db` | float | `-50.0` | Mean volume (dB) a second must reach to count as audible |
| `--prepare-audio` | bool | `true` | Put the sound up before the watch window (read the mute state, clear a mute, raise the volume) |
| `--volume-presses` | int | `20` | How many `VOLUME_UP` presses bring the volume to the maximum |
| `--max-freeze-s` | float | `5.0` | Longest tolerated freeze / black window |
| `--no-navigate` | bool | `false` | Watch the current screen instead of navigating to `--node` |
| `--verify` | string | `end` | `end` (destination only), `each` (every step), `auto` |

## The sound is put up before the watch

A device that is **muted**, or whose **volume is at 0**, is silent without being
broken. So before the watch window the check:

1. asks the device whether it is **muted** — a browser player says (`video.muted`),
   a set-top box with a remote does not (it shows no mute icon on the picture), and
   the report says which of the two it is rather than guessing;
2. **clears a mute** it can see (a video that autoplays muted is silent while
   everything is fine);
3. **raises the volume to the maximum** (`VOLUME_UP` × `--volume-presses`), because a
   volume at 0 is a reason for silence that has nothing to do with the device.

**The script never presses `MUTE`.** Muting the device to make the check fail would
be the script creating the failure it then reports. When the audio verdict fails, the
reason names the cause the check actually knows:

| Situation | The reason in the report |
|-----------|--------------------------|
| The device says it is muted | `audio: the device is muted` |
| The device says it is **not** muted | `audio: present for less than X % of the window (the device is not muted)` |
| The device cannot say | `audio: present for less than X % of the window (the volume was raised to the maximum, the mute state is unknown)` |

## Output

The report shows the evidence, not just a badge:

- **Verdict video / audio**, with the reason on failure.
- **The two frames the motion check compared** and the measured change % (fullzap style),
  plus a screenshot at the **start / middle / end** of the window.
- **A table with the audio level (dB) of every second** of the window, next to the step
  that carries the verdict.
- **Silence windows** and **freeze / black windows**, with their positions in the window.
- **Total audio-present %** and **motion-present %** for the window.

The **executive summary** is the verdict and stays short: the per-second levels live in
the table of the step, not in a wall of text that cannot be read at a glance.

The freeze and motion verdicts are built from what the platform **measured**, not from
the per-frame `freeze` flag alone. The capture monitor compares every frame with the
previous ones and writes the pixel difference it found in `freeze_diffs`, and its own
verdict on it in `freeze` (True when none of those differences reached the platform's
`FREEZE_THRESHOLD`). The script reads both:

- a second **moved** when at least one of its frames saw a change;
- a **freeze** is the *gap* in which the picture never changed — between two of those
  moments, or between one of them and the edge of the watch window. Only a gap
  longer than `--max-freeze-s` counts as a freeze.

Both steps matter. The per-frame `freeze` flag answers "was this frame identical to
the one before it", which is a statement about the *capture pipeline*: a grabber
that repeats the same picture for several frames in a row (a phone on a slow HDMI
mirror does exactly that) is flagged on every repeat, so counting the flags reports
a playing video as frozen for the whole window. And a picture that only updates
every second or two puts no change at all inside most one-second buckets, so
counting "the seconds without a change" would report it as frozen too. The picture
that stops moving is the one that leaves a gap as wide as the time it stood still.

A capture pipeline that writes no pixel difference at all falls back to the flags it
does write — the monitor's own per-frame `motion` verdict, then the `freeze` flag — on
the same majority rule the platform's own `analysis_utils.get_motion_analysis` uses.

**Motion present %** is the share of the window in which the picture was not stuck for
longer than `--max-freeze-s`, read from the same gaps the freeze verdict uses, so the
two always agree.

## What it reuses

No detection is re-implemented. Every verdict comes from the platform's own code:

| Need | Code |
|------|------|
| Navigate to the node | `NavigationExecutor.execute_navigation` (the same call `goto.py` makes) |
| Per-second audio level, freeze, blackscreen | `backend_host.src.lib.utils.analysis_utils.load_recent_analysis_data_from_path` — the capture monitor's per-frame JSON, the same source the `DetectMotionFromJson` verification reads. Its `freeze_diffs` / `freeze` are the platform's own measurement of "did the picture move" |
| Motion between two frames | `ZapExecutor.detect_real_motion` → the `DetectMotion` video verification → `video_analysis_helpers.compare_images_for_motion` |
| Screenshots | `device_utils.capture_screenshot_for_script` |

## Notes

- The tree must contain the node you point at. If it does not, the run stops with
  `Navigation failed` — no taps are hard-coded.
- A device with **no remote, browser or desktop** (an HLS / RTSP box) has no UI to
  drive. The script detects that and watches the screen it is showing instead of
  failing on a key press that cannot happen. `--no-navigate` forces the same behaviour
  on any device.
- The watch window is measured on the capture monitor's frames. A device whose monitor
  profile is `tv_lite` has no per-frame analysis at all; the script says so instead of
  inventing a verdict.
- When the capture has **no signal** (the platform's own `no_signal` flag), the video
  verdict fails with `no signal from the device` rather than the misleading
  `no motion detected`.

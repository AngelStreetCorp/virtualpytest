# YouTube Video Check (`youtube_video_check`)

## Purpose

Opens YouTube, validates consent/cookie state, opens a target video, handles ads and premium popups, and verifies playback progression.

## Target Environment

- Host-targeted web script.
- Uses the device web controller during normal VirtualPyTest execution.
- Supports local-debug Playwright execution with `--local-debug`.

## Usage

```bash
python test_scripts/web/youtube_video_check.py
python test_scripts/web/youtube_video_check.py --url "https://www.youtube.com/watch?v=y9n6HkftavM"
python test_scripts/web/youtube_video_check.py --ad_wait 30 --monitor_duration 30
python test_scripts/web/youtube_video_check.py --local-debug --headless false --monitor_duration 20
```

## Parameters

Run Tests UI / script arguments:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--url` | string | `https://www.youtube.com/watch?v=y9n6HkftavM` | YouTube video URL |
| `--ad_wait` | int | `30` | Seconds to wait when an ad cannot be skipped |
| `--monitor_duration` | int | `30` | Playback monitoring window in seconds |
| `--headless` | bool | `false` | Browser headless mode for local-debug execution |

Local-debug CLI behavior:

- `--local-debug` bypasses decorated device setup and runs a host Playwright flow.
- Local-debug accepts `--url`, `--ad_wait`, `--monitor_duration`, and `--headless`.

## Behavior

1. Opens a browser session.
2. Navigates to `https://www.youtube.com`.
3. Validates whether consent cookies were injected and whether a consent modal remains visible.
4. Dismisses the consent modal if needed.
5. Opens the configured video URL.
6. Checks for ads, skips them when possible, or waits `--ad_wait` seconds for unskippable ads.
7. Attempts to force playback.
8. Monitors video status and `currentTime` progression for `--monitor_duration`.
9. Dismisses the premium popup once after playback reaches the configured threshold.

## Outputs and Metadata

Stored metadata includes:

- `url`
- `cookie_result`
- `ad_result`
- `video_result.playing`
- `video_result.progress_seconds`
- `video_result.sample_count`
- `page_load_time_ms` — page-load time (see [Timing Metrics](#timing-metrics))
- `video_load_time_ms` — video buffering / time-to-first-frame (see [Timing Metrics](#timing-metrics))
- `first_frame_method` — which browser signal produced `video_load_time_ms`
- `mode`
- `target_url`
- local-debug `trace_path` and screenshot count when applicable

Reports include step screenshots for YouTube home state, consent handling, video open, ad handling, and playback monitoring.

## Timing Metrics

Two timings are reported in metadata and surfaced on the Grafana SRI dashboard as the **Page Load** and **Video Buffering** columns.

### `page_load_time_ms` — page load

Python wall-clock wrapped around the single navigation call to the video URL, measured from the start of navigation until the browser reports `domcontentloaded`. This is essentially network + document load; it does **not** include player init, ad handling, or video buffering.

### `video_load_time_ms` — video buffering / time-to-first-frame

Measured **inside the browser**, not in Python. Immediately after the video page navigates, the script installs a first-frame probe (`WEB_JS_INSTALL_FIRST_FRAME_PROBE`) on the freshly-loaded document. The probe records `performance.now()` at the moment the **first video frame is actually painted to screen**:

- **Primary signal — `HTMLVideoElement.requestVideoFrameCallback`**: the browser's own "a frame was just presented" callback, and the most accurate first-frame timestamp available.
- **Fallback** (engines without rVFC): the first `playing` / `timeupdate` media event with `readyState ≥ 3` and `currentTime > 0`.

Because `performance.now()` is relative to the page's navigation `timeOrigin`, the recorded value **is** the number of milliseconds from opening the video page to the first painted frame — real startup/buffering time, measured end-to-end in the page and therefore **immune to the script's own ad-handling sleeps**.

Semantics are **"first frame of whatever plays"** — for YouTube a pre-roll ad counts as the first frame; the probe does not try to distinguish ad from content. The companion field `first_frame_method` records which signal produced the value:

| `first_frame_method` | Meaning |
|---|---|
| `rvfc` | `requestVideoFrameCallback` fired — most accurate |
| `playing` | first `playing` event (rVFC unavailable) |
| `timeupdate` | first `timeupdate` with time > 0 (last-resort browser signal) |
| `already-playing` | a frame was already on screen when the probe installed; value is a **floor**, not exact |

> **Why this replaced the old metric.** Previously `video_load_time_ms` was a Python wall-clock from page-load to the first *polled* "playing" sample, and that assignment lives inside the monitor loop — which only runs **after** the entire ad-handling phase (up to a 30 s skip poll + a 40 s fallback wait). So the value was dominated by those fixed sleeps and could read **minutes** even when the video actually started in ~1 s. The old wall-clock is now kept only as a last-resort fallback if no in-page first-frame signal ever fires.

## Dashboard

No dedicated Grafana dashboard is documented for this script. Results are reviewed through script results, reports, metadata, screenshots, and traces.

## Troubleshooting

- If a consent modal remains visible after cookie injection, the script fails early and stores the modal selector in metadata.
- If playback does not progress, inspect `video_result.sample_count`, `progress_seconds`, and screenshots.
- If ads block playback, increase `--ad_wait` or inspect the ad-handling step result.

## Related Documentation

- [Facebook Check](./facebook_check.md)
- [Netflix Video Check](./netflix_video_check.md)

# Facebook Check (`facebook_check`)

## Purpose

Opens the Example Facebook videos page, handles common overlays, starts playback, and verifies video time progression.

## Target Environment

- Host-targeted web script.
- Uses the device web controller during normal VirtualPyTest execution.
- Supports local-debug Playwright execution with `--local-debug`.

## Usage

```bash
python test_scripts/web/facebook_check.py
python test_scripts/web/facebook_check.py --url "https://www.facebook.com/Example.ch/videos/?ref=page_internal&locale=en_EN"
python test_scripts/web/facebook_check.py --monitor_duration 20 --browser_fullscreen true
python test_scripts/web/facebook_check.py --local-debug --headless false
```

## Parameters

Run Tests UI / script arguments:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--url` | string | `https://www.facebook.com/Example.ch/videos/?ref=page_internal&locale=en_EN` | Facebook videos page URL |
| `--monitor_duration` | int | `20` | Playback monitoring window in seconds |
| `--browser_fullscreen` | bool | `true` | Press fullscreen key before playback monitoring |
| `--headless` | bool | `false` | Browser headless mode for local-debug execution |

Local-debug CLI behavior:

- `--local-debug` bypasses decorated device setup and runs a host Playwright flow.
- `--headless` and `--browser_fullscreen` are accepted by the local-debug CLI.

## Behavior

1. Navigates to the configured Facebook videos page.
2. Closes cookie prompts best-effort.
3. Closes the login popup via the close aria label.
4. Waits for player readiness.
5. Clicks play, toggles mute/unmute, and enters fullscreen when enabled.
6. Samples video state and verifies playback progression over the monitor window.
7. Retries bounded playback monitoring when no progress is detected.

## Outputs and Metadata

The script stores step results, screenshots, execution summary, and metadata including:

- `mode`
- `target_url`
- `cookie_clicks`
- `popup_closed`
- `player_ready`
- `playing`
- `progress_seconds`
- `page_load_time_ms` — page-load time (see [Timing Metrics](#timing-metrics))
- `video_load_time_ms` — video buffering / time-to-first-frame (see [Timing Metrics](#timing-metrics))
- `first_frame_method` — which browser signal produced `video_load_time_ms`
- `browser_fullscreen`
- local-debug screenshot count/report artifacts when run with `--local-debug`

## Timing Metrics

Two timings are reported in metadata and surfaced on the Grafana SRI dashboard as the **Page Load** and **Video Buffering** columns.

### `page_load_time_ms` — page load

Python wall-clock wrapped around the single navigation call to the videos page, measured from the start of navigation until the browser reports `domcontentloaded`. This is essentially network + document load; it does **not** include player init or video buffering.

### `video_load_time_ms` — video buffering / time-to-first-frame

Measured **inside the browser**, not in Python. Immediately after the page navigates, the script installs a first-frame probe (`WEB_JS_INSTALL_FIRST_FRAME_PROBE`) on the freshly-loaded document. The probe records `performance.now()` at the moment the **first video frame is actually painted to screen**:

- **Primary signal — `HTMLVideoElement.requestVideoFrameCallback`**: the browser's own "a frame was just presented" callback, and the most accurate first-frame timestamp available.
- **Fallback** (engines without rVFC): the first `playing` / `timeupdate` media event with `readyState ≥ 3` and `currentTime > 0`.

Because `performance.now()` is relative to the page's navigation `timeOrigin`, the recorded value **is** the number of milliseconds from opening the page to the first painted frame — real startup/buffering time, measured end-to-end in the page and therefore **immune to the script's own play-retry/wait loops**.

Semantics are **"first frame of whatever plays"**; the probe does not distinguish ad from content. The companion field `first_frame_method` records which signal produced the value:

| `first_frame_method` | Meaning |
|---|---|
| `rvfc` | `requestVideoFrameCallback` fired — most accurate |
| `playing` | first `playing` event (rVFC unavailable) |
| `timeupdate` | first `timeupdate` with time > 0 (last-resort browser signal) |
| `already-playing` | a frame was already on screen when the probe installed; value is a **floor**, not exact |

> **Why this replaced the old metric.** Previously `video_load_time_ms` was a Python wall-clock from page-load to the first *polled* "playing" sample, set inside the bounded play-retry monitor loop — so it was inflated by the script's retry/wait timing rather than reflecting actual buffering. The old wall-clock is now kept only as a last-resort fallback if no in-page first-frame signal ever fires.

## Dashboard

No dedicated Grafana dashboard is documented for this script. Results are reviewed through script results, reports, metadata, and screenshots.

## Troubleshooting

- If playback fails with no progress, inspect screenshots and the final video status samples.
- Facebook overlay behavior can change; cookie and login popup handling is best effort.

## Related Documentation

- [YouTube Video Check](./youtube_video_check.md)
- [Netflix Video Check](./netflix_video_check.md)

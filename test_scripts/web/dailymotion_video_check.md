# Dailymotion Video Check (`dailymotion_video_check`)

## Purpose

Opens Dailymotion, handles the Sourcepoint cookie consent modal, navigates to a specific video, starts playback, and verifies video time progression.

## Target Environment

- Host-targeted web script.
- Uses the device web controller during normal VirtualPyTest execution.
- Supports local-debug Playwright execution with `--local-debug`.

## Usage

```bash
python test_scripts/web/dailymotion_video_check.py
python test_scripts/web/dailymotion_video_check.py --url "https://www.dailymotion.com/video/xa2wwo4"
python test_scripts/web/dailymotion_video_check.py --monitor_duration 20 --preroll_wait 10
python test_scripts/web/dailymotion_video_check.py --local-debug --headless false
```

## Parameters

Run Tests UI / script arguments:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--url` | string | `https://www.dailymotion.com/video/xa2wwo4` | Dailymotion video URL |
| `--preroll_wait` | int | `15` | Seconds to wait for a pre-roll ad before monitoring |
| `--monitor_duration` | int | `30` | Playback monitoring window in seconds |
| `--headless` | bool | `false` | Browser headless mode for local-debug execution |

Local-debug CLI behavior:

- `--local-debug` bypasses decorated device setup and runs a host Playwright flow.
- `--headless` is accepted by the local-debug CLI.

## Behavior

1. Navigates to `https://www.dailymotion.com` (the `/fr` locale path triggers a Chrome GPU crash via the CDP launcher flags, so the bare origin is used).
2. Detects the Sourcepoint cookie consent modal and clicks the Accept button inside its cross-origin iframe (`sp_message_iframe_*` from `consent.dailymotion.com`). Falls back to an in-page JS dismissal for other CMPs.
3. Extracts the Dailymotion video id from `--url` and navigates to the embed player at `https://geo.dailymotion.com/player.html?video=<id>&mute=1&autoplay=1`. The `/video/<id>` SPA route fails to hydrate under the CDP launcher's GPU flags and serves a bare-HTML fallback with no `<video>` element, so the script uses the embed player instead.
4. Dismisses the player's in-frame tracker banner via its close button and clicks the `.vod_click` overlay to start playback.
5. Forces playback via `video.play()` and attempts fullscreen.
6. Waits `preroll_wait` seconds for any pre-roll ad (Dailymotion ads play into the same `<video>` element, so monitoring still catches progression).
7. Samples `<video>` state and verifies playback progression over the monitor window.

## Outputs and Metadata

The script stores step results, screenshots, execution summary, and metadata including:

- `mode`
- `url`
- `cookie_result` (modal detection, dismissal method, post-dismiss state)
- `video_result` (playing, progress_seconds, sample_count)
- `page_load_time_ms` — page-load time (see [Timing Metrics](#timing-metrics))
- `video_load_time_ms` — video buffering / time-to-first-frame (see [Timing Metrics](#timing-metrics))
- `first_frame_method` — which browser signal produced `video_load_time_ms`
- `headless`
- `trace_path` and `test_video_path` when run with `--local-debug`
- local-debug screenshot count/report artifacts when run with `--local-debug`

## Timing Metrics

Two timings are reported in metadata and surfaced on the Grafana SRI dashboard as the **Page Load** and **Video Buffering** columns.

### `page_load_time_ms` — page load

Python wall-clock wrapped around the single navigation call to the embed-player page, measured from the start of navigation until the browser reports `domcontentloaded`. This is essentially network + document load; it does **not** include player init, the tracker-banner dismissal, the pre-roll ad, or video buffering.

### `video_load_time_ms` — video buffering / time-to-first-frame

Measured **inside the browser**, not in Python. Immediately after the embed page navigates, the script installs a first-frame probe (`WEB_JS_INSTALL_FIRST_FRAME_PROBE`) on the freshly-loaded document. The probe records `performance.now()` at the moment the **first video frame is actually painted to screen**:

- **Primary signal — `HTMLVideoElement.requestVideoFrameCallback`**: the browser's own "a frame was just presented" callback, and the most accurate first-frame timestamp available.
- **Fallback** (engines without rVFC): the first `playing` / `timeupdate` media event with `readyState ≥ 3` and `currentTime > 0`.

Because `performance.now()` is relative to the page's navigation `timeOrigin`, the recorded value **is** the number of milliseconds from opening the embed page to the first painted frame — real startup/buffering time, measured end-to-end in the page and therefore **immune to the script's own banner-dismiss and pre-roll waits**.

Semantics are **"first frame of whatever plays"** — for Dailymotion the pre-roll ad shares the same `<video>` element and counts as the first frame. The companion field `first_frame_method` records which signal produced the value:

| `first_frame_method` | Meaning |
|---|---|
| `rvfc` | `requestVideoFrameCallback` fired — most accurate |
| `playing` | first `playing` event (rVFC unavailable) |
| `timeupdate` | first `timeupdate` with time > 0 (last-resort browser signal) |
| `already-playing` | a frame was already on screen when the probe installed; value is a **floor**, not exact |

> **Why this replaced the old metric.** Previously `video_load_time_ms` was a Python wall-clock from page-load to the first *polled* "playing" sample, set inside the monitor loop — which only runs after the tracker-banner dismissal and the `preroll_wait` sleep. So the value was dominated by those fixed waits rather than reflecting actual buffering. The old wall-clock is now kept only as a last-resort fallback if no in-page first-frame signal ever fires.

## Dashboard

No dedicated Grafana dashboard is documented for this script. Results are reviewed through script results, reports, metadata, and screenshots.

## Troubleshooting

- If playback fails with no progress, inspect screenshots and the final video status samples.
- The Dailymotion `/video/<id>` route fails to hydrate its React player bundle under the CDP launcher's `--use-gl=swiftshader` / `--disable-gpu` flags and serves a bare-HTML fallback. The script works around this by navigating to the embed URL at `geo.dailymotion.com/player.html?video=<id>` which exposes a usable `<video>` element.
- Dailymotion's CMP is Sourcepoint and lives inside a cross-origin iframe (`sp_message_iframe_*` from `consent.dailymotion.com`) — consent handling relies on Playwright frame locators rather than page-level JS.
- Visiting `https://www.dailymotion.com/fr` (with locale) crashes the Chrome GPU process under the CDP launcher flags; the script uses the bare origin and lets the server redirect based on locale.

## Related Documentation

- [YouTube Video Check](./youtube_video_check.md)
- [Facebook Check](./facebook_check.md)
- [Netflix Video Check](./netflix_video_check.md)

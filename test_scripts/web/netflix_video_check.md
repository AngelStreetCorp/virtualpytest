# Netflix Video Check (`netflix_video_check`)

## Purpose

Logs into Netflix, selects a required profile, opens a target video, and verifies playback progression.

## Target Environment

- Host-targeted web script.
- Uses the device web controller during normal VirtualPyTest execution.
- Supports local-debug Playwright execution with `--local-debug`.
- Netflix DRM/protected-content restrictions can block playback in some browser environments.

## Usage

```bash
python test_scripts/web/netflix_video_check.py \
  --email "your_email@example.com" \
  --password "your_password" \
  --profile "Manual Testing"

python test_scripts/web/netflix_video_check.py \
  --local-debug \
  --headless false \
  --email "your_email@example.com" \
  --password "your_password" \
  --profile "Manual Testing" \
  --url "https://www.netflix.com/watch/81450642"
```

## Parameters

Run Tests UI / script arguments:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--email` | string | empty | Netflix account email; required |
| `--password` | string | empty | Netflix account password; required |
| `--profile` | string | `Kids` | Profile name to select after login |
| `--url` | string | `https://www.netflix.com/watch/81450642` | Netflix watch URL |
| `--login_url` | string | `https://www.netflix.com/login` | Netflix login page URL |
| `--post_login_wait` | int | `8` | Wait time after login submit |
| `--monitor_duration` | int | `30` | Playback monitoring window in seconds |
| `--headless` | bool | `false` | Browser headless mode for local-debug execution |

Local-debug CLI behavior:

- `--local-debug` bypasses decorated device setup and runs a host Playwright flow.
- The local-debug CLI accepts the same fields above.
- `--channel` and `--user_data_dir` are not script-declared arguments in the current implementation.

## Behavior

1. Opens the Netflix login page.
2. Dismisses the cookie banner.
3. Fills and submits the login form.
4. Validates login state by checking `/browse` or the profile gate.
5. Selects the requested profile when the profile gate is shown.
6. Opens the watch URL.
7. Attempts playback via play button and `video.play()`.
8. Detects DRM/protected-content block `M7701-1003`.
9. Monitors `video.currentTime` progression for `--monitor_duration`.

## Outputs and Metadata

Stored metadata includes:

- `url`
- `profile`
- `login_result`
- `profile_result`
- `video_result.playing`
- `video_result.progress_seconds`
- `video_result.sample_count`
- `video_result.error`
- `mode`
- `target_url`
- local-debug `trace_path` and screenshot count when applicable

## Dashboard

No dedicated Grafana dashboard is documented for this script. Results are reviewed through script results, reports, metadata, screenshots, and traces.

## Troubleshooting

- Missing `--email`, `--password`, or `--profile` fails before playback.
- If playback fails with `M7701-1003`, the browser environment is blocked by Netflix protected-content/DRM requirements.
- Cookie-banner handling runs at login and playback stages, but Netflix UI changes can require selector updates.

## Related Documentation

- [YouTube Video Check](./youtube_video_check.md)
- [Facebook Check](./facebook_check.md)

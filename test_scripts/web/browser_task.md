# Browser Task (`browser_task`)

## Purpose

Navigates to a URL, waits for the page to settle, and executes a browser-use AI task with a bounded number of steps.

## Target Environment

- Host-targeted web script.
- Uses the device web controller during normal VirtualPyTest execution.
- Supports local-debug Playwright execution with `--local-debug`.
- The browser-use model is the `agent.browser` AI route (Settings → AI; must be an OpenAI-compatible
  profile). Calls go through the server passthrough `/server/ai/openai/agent.browser`, so local-debug
  needs `SERVER_URL` + `API_KEY` for a server, not a provider key.

## Usage

```bash
python test_scripts/web/browser_task.py --url "google.com" --task "Search for Python tutorials"
python test_scripts/web/browser_task.py --url "https://youtube.com" --task "Find a video about cats" --max_steps 10
python test_scripts/web/browser_task.py --local-debug --url "youtube.com" --task "Launch funny cat video"
```

## Parameters

Run Tests UI / script arguments:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--url` | string | `youtube.com` | URL to navigate to |
| `--task` | string | `Launch funny cat video` | Browser-use task description |
| `--max_steps` | int | `10` | Maximum browser-use agent steps |
| `--wait_seconds` | int | `10` | Wait time before task execution |

Local-debug CLI behavior:

- `--local-debug` bypasses decorated device setup and runs a host Playwright flow.
- Local-debug accepts `--url`, `--task`, `--max_steps` and `--wait_seconds`.

## Behavior

1. Opens or connects to a browser session.
2. Normalizes and navigates to the requested URL.
3. Handles YouTube consent modal dismissal for YouTube targets.
4. Waits `--wait_seconds`.
5. Runs the browser-use AI task with `--max_steps`.
6. Captures screenshots, logs, trace artifacts, final URL, page title, and task result.

## Outputs and Metadata

Stored metadata includes:

- `mode`
- `url`
- `task`
- `max_steps`
- `navigation_result`
- `task_result`
- `final_url`
- `page_title`
- `trace_path`
- `test_video_path`
- `screenshot_count`

The execution summary includes navigation status, wait duration, browser-use task status, result summary, execution logs when available, screenshot count, and final error when present.

## Dashboard

No dedicated Grafana dashboard is documented for this script. Results are reviewed through script results, reports, metadata, screenshots, traces, and optional test video output.

## Troubleshooting

- If browser-use fails before the first step, check the `agent.browser` route in Settings → AI → Routing
  (it must resolve to an OpenAI-compatible profile with a working key — press Test) and that
  `SERVER_URL` / `API_KEY` reach the server.
- If task execution fails, inspect `task_result.error` and truncated execution logs in the report.

## Related Documentation

- [Example TV Go Home](./exampletv_go_home.md)
- [YouTube Video Check](./youtube_video_check.md)

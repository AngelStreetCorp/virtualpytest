# Browser Task (`browser_task`)

## Purpose

Navigates to a URL, waits for the page to settle, and executes a browser-use AI task with a bounded number of steps.

## Target Environment

- Host-targeted web script.
- Uses the device web controller during normal VirtualPyTest execution.
- Supports local-debug Playwright execution with `--local-debug`.
- Local-debug browser-use requires an OpenRouter API key supplied by argument or environment.

## Usage

```bash
python test_scripts/web/browser_task.py --url "google.com" --task "Search for Python tutorials"
python test_scripts/web/browser_task.py --url "https://youtube.com" --task "Find a video about cats" --max_steps 10
python test_scripts/web/browser_task.py --local-debug --url "youtube.com" --task "Launch funny cat video" --openrouter_api_key "$OPENROUTER_API_KEY"
```

## Parameters

Run Tests UI / script arguments:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--url` | string | `youtube.com` | URL to navigate to |
| `--task` | string | `Launch funny cat video` | Browser-use task description |
| `--max_steps` | int | `10` | Maximum browser-use agent steps |
| `--wait_seconds` | int | `10` | Wait time before task execution |
| `--openrouter_api_key` | string | empty | Optional OpenRouter API key for local-debug browser-use |

Local-debug CLI behavior:

- `--local-debug` bypasses decorated device setup and runs a host Playwright flow.
- Local-debug accepts `--url`, `--task`, `--max_steps`, `--wait_seconds`, and `--openrouter_api_key`.

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
- `openrouter_api_key_provided`
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

- If local-debug browser-use fails with a missing API key, provide `--openrouter_api_key` or configure `OPENROUTER_API_KEY`.
- If task execution fails, inspect `task_result.error` and truncated execution logs in the report.

## Related Documentation

- [Example TV Go Home](./exampletv_go_home.md)
- [YouTube Video Check](./youtube_video_check.md)

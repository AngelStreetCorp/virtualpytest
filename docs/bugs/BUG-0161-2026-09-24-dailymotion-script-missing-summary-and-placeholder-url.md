# BUG-0161 — Dailymotion script: missing Execution Summary + placeholder URL crash

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0161                                                     |
| Reported  | 2026-09-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / test_scripts                                  |
| Fixed in  | build 9364                                                   |
| Commit    | eef478a79b                                                   |

---

## Symptom

Two distinct symptoms hit `test_scripts/web/dailymotion_video_check.py` and degraded the operator view of any failed run:

1. **Placeholder URL crash.** A `dailymotion_video_check` run on `host-clone-1` (script_result `6bc6adcc-79a9-4b27-a1d3-290336bb8f41`) failed instantly with:

   ```
   🎯 [dailymotion_video_check] URL: {_DEFAULT_VIDEO_URL}
   ❌ [dailymotion_video_check] Test failed: Could not extract a video id from --url: {_DEFAULT_VIDEO_URL}
   ```

   The literal 21-character string `{_DEFAULT_VIDEO_URL}` (with curly braces) was passed in as `args.url`. The script's `RuntimeError`/`context.error_message` then surfaced it as the URL value, which is misleading — the constant resolves to a real Dailymotion URL.

2. **Missing Execution Summary in the report.** Every `dailymotion_video_check` failure (including the one above) showed the placeholder block at the top of the report:

   ```
   📊 Execution summary not available
   ℹ️  This may be from an older script run
   🔄 Run the script again to see detailed summary
   ```

   instead of useful run details.

The trigger for both is upstream — some caller (scheduler row, MCP request, or frontend form) forwarded the literal `{_DEFAULT_VIDEO_URL}` placeholder instead of the substituted URL. The script had no defence.

## Root cause

**Symptom 1 — placeholder URL crash.**
`_DEFAULT_VIDEO_URL` is defined as the Python f-string template `--url:str:{_DEFAULT_VIDEO_URL}` at the top of `test_scripts/web/dailymotion_video_check.py`. The argparser in `shared/src/lib/executors/script_decorators.py` (around `build_parser_for_script`) correctly splits + rejoins the colon-bearing `https://` URL and produces the real default, so omitting `--url` is fine. The crash only happens when `--url {_DEFAULT_VIDEO_URL}` is passed explicitly. `_extract_video_id` does a pure regex match (`r'/video/([^/?#]+)'`) and returns `None` for the placeholder; the script then raises / sets the error message without any fallback.

**Symptom 2 — missing Execution Summary.**
The device-controller path of `main()` sets `context.error_message` / `context.overall_success` / `context.step_results` at every early-return (the "no web controller", "browser open failed", "navigate to home failed", "could not extract video id", and "navigate to embed failed" branches) and at the final return, but **never sets `context.execution_summary`**. The report pipeline reads it via `script_executor.py` → `report_generation_utils.py` → `format_console_summary_for_html` (in `shared/src/lib/utils/report_formatting.py`) which renders the "Execution summary not available" fallback when the value is empty.

The same convention is followed by `facebook_check.py`, `device_get_info.py`, `goto.py`, `kpi_measurement.py`, etc. — `dailymotion_video_check.py` simply never adopted it for its device-controller path. The local-debug `capture_local_execution_summary` helper was wired up, but no `_summary()` for the host run.

## Fix

Two changes in `test_scripts/web/dailymotion_video_check.py`:

1. **URL fallback.** Added `_resolve_video_url(url) -> str` that returns `url` when it parses as a Dailymotion `/video/<id>` URL, otherwise returns `_DEFAULT_VIDEO_URL`. `main()` now calls it once near the top:

   ```python
   video_url = _resolve_video_url(args.url)
   ```

   so a placeholder or any malformed value silently falls back to the canonical default. The local-debug `_run_local_playwright_flow` deliberately still raises on a bad URL — silent substitution would hide real developer typos.

2. **Execution Summary on every return path.** Added `_summary(context, url, data) -> str` mirroring the pattern used in `facebook_check.py`. `main()` now assigns `context.execution_summary = _summary(context, video_url, {...})` at every early-return and at the final return, so the report's "Execution Summary" block always renders the URL, video id, playback result, progress, load times, and error instead of the fallback.

The `capture_local_execution_summary` helper (used by the `--local-debug` flow) is untouched.

## Verification

- Manual unit checks against `_resolve_video_url` covered: valid Dailymotion URL → kept verbatim; literal `{_DEFAULT_VIDEO_URL}` → fallback; `None` / `''` → fallback; arbitrary garbage → fallback; another valid `/video/<id>` URL → kept verbatim; a non-Dailymotion URL → fallback.
- `_summary` renders correctly with empty data (failure), full data (success), and a placeholder URL (still produces a coherent report — `Video ID: -`, error message present).
- `python3 -c 'import ast; ast.parse(...)'` confirms the file still parses; AST walk finds `_extract_video_id`, `_resolve_video_url`, `_summary`, and `main` as expected.
- `scripts/docs/check_bug_meta.py` and `scripts/docs/check_bug_ids.sh` both pass on this entry.
- End-to-end: re-run `dailymotion_video_check` on a normal host with a real `--url` (or no `--url`) — report's Execution Summary shows the run details. Re-run with `--url {_DEFAULT_VIDEO_URL}` — script no longer crashes, falls back to the default, summary shows the resolved URL.
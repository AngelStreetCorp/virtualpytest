# BUG-0067 — `web-script-local-debug` CI job green while both scripts printed `SCRIPT_SUCCESS:false`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0067                                                                    |
| Reported  | 2026-09-08                                                                  |
| Status    | Fixed                                                                       |
| Severity  | Medium — a CI job that cannot fail hides real regressions                   |
| Area      | tests/test_scripts/run_web_local_debug.sh (CI job web-script-local-debug)   |
| Fixed in  | build 8887                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

Run #340's `web-script-local-debug` report header said **PASSED** while its own output ended with

```
🎯 Result: FAILED
❌ Error: Video playback not confirmed during monitoring window
SCRIPT_SUCCESS:false
...
Error: Browser-use task failed: Browser-use not available: No module named 'browser_use'
SCRIPT_SUCCESS:false
```

## Root cause

VPT scripts always exit 0 and report their verdict as a `SCRIPT_SUCCESS:true|false` line on stdout
(`local_debug_browser_helpers.py`, `browser_task.py`); the platform's `script_executor` parses that
marker. The CI runner script only propagated the exit code, so a failed script and a passed one
looked the same to `steps.run-scripts.outcome`.

## Fix

`run_web_local_debug.sh` captures each script's output, requires a `SCRIPT_SUCCESS:true` line,
and exits 1 naming every script that did not produce one (a crash without a marker counts as a
failure). Verified with stub scripts: false marker → 1, true → 0, crash → 1.

## The two failures it was hiding — root causes and fixes

1. **`youtube_video_check`: "Video playback not confirmed"** — the screenshot the runner
   captured shows YouTube's interstitial *"Sign in to confirm you're not a bot"*: no `<video>`
   at all. The runner (VM 164) egresses through the Hetzner datacenter IP with a fresh profile,
   which YouTube challenges. Not an audio/autoplay problem (the ALSA lines are noise).
   Probed on the runner with Playwright's own Chromium and with `/usr/bin/chromium`: same
   interstitial, media requests answer 403 — no browser choice gets around it. Fix: the CI
   smoke runs `dailymotion_video_check.py` instead (its `geo.dailymotion.com` player plays
   headlessly on the runner: position 20 s → 25 s, first frame 2.9 s, `SCRIPT_SUCCESS:true`).
   `youtube_video_check.py` stays a host-tier script; it now checks for the interstitial
   right after opening the watch page (`YOUTUBE_JS_CHECK_BOT_WALL`) and fails fast with that
   exact reason instead of blaming playback. From a residential IP it still passes.
2. **`browser_task`: `No module named 'browser_use'`** — the job's pip step never installed
   it. Fix: `browser-use==0.7.1` (same as the web host sample-app-web) plus `pydantic-settings`,
   which 0.7.1 imports but does not declare. Verified locally: task on example.com completes,
   `SCRIPT_SUCCESS:true`.

# BUG-0757 — With two browser runs on one host, a report's screenshot showed the other run's browser

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0757                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium (the report of a run shows evidence from a different run; nothing is lost, but the report is not evidence of anything) |
| Area      | testing / backend                                            |
| Fixed in  | build 90145 |
| Commit    | 8b37ab987                                                    |

---

## Symptom

Two web scripts running at the same time on one host (TASK-146) finish with reports whose step
screenshots belong to **the other run**: the YouTube report shows Dailymotion, or both show
whichever window was on top when the capture happened. The verdict and the captured data are
correct, so the run is not wrong — but the image the reader uses to judge the run is.

It only shows with two runs on the host. One run alone is fine, because then it is the only
Chrome on the screen.

## Root cause

**A host has one screen, and every browser run on it draws there.** The display is shared by
construction: `DISPLAY=:1` is the host's single TigerVNC screen (`vpt-vnc.service`), and
`browser_window_utils.build_window_flags()` puts every Chrome window at the same bounds on it
(detected from `xrandr`, `shared/src/lib/utils/browser_window_utils.py:110`). With one run that
is fine. With two, their windows overlap, and the one on top owns the pixels.

The report's screenshots came from that screen. `capture_screenshot_for_script()` asked the AV
controller for an image (`shared/src/lib/utils/device_utils.py`), which is
`FFmpegCaptureController.take_screenshot()`: it returns **the newest file in the host's capture
folder**, written continuously by the host's own x11grab loop at 2 fps
(`backend_host/src/controllers/base_controller.py:412`). That is a photograph of the whole
screen, taken by a loop that knows nothing about which run asked for it. Whoever's window is on
top is whoever's page is in the picture.

Every web script takes its step images through this path (`youtube_video_check.py`,
`dailymotion_video_check.py`, `netflix_video_check.py`, `facebook_check.py` all call
`capture_screenshot_for_script`). TASK-146 gave every run its own debug port and its own Chrome
profile; the screen stayed shared, so this was the one part of the isolation left open — and
[TASK-146](../tasks/TASK-146-parallel-browser-runs-one-host.md) named it as the known
limitation.

The obvious alternative, an Xvfb per run, was rejected: a second X server per run costs memory
that [BUG-0743](BUG-0743-2026-10-21-a-host-could-carry-unlimited-browser-tests-at-once.md)
just started budgeting against, and the run's window would then be invisible to the host's
capture and monitoring loop, so the device would stop being observable while a test runs on it.

## Fix

**A report photographs the run's own page**, not the screen.

- `PlaywrightWebController.capture_page_screenshot()`
  (`backend_host/src/controllers/web/playwright.py`) photographs the run's own page through the
  browser that run already drives, and returns the path. It never opens a page: a screenshot
  must not change what the run is doing, so it returns `None` when there is no live page. A dead
  browser (`TargetClosedError`) is a `None`, not an exception.
- `capture_run_page_screenshot()` (`shared/src/lib/utils/device_utils.py`) is the bridge: it asks
  the device for its `web` controller and writes into
  `$TMPDIR/virtualpytest_run_shots/<run id>/<ns>_<step id>.png` — one directory per run, so two
  runs can never write over each other.
- **Both** screenshot paths try that first and keep the screen capture as their own fallback:
  `capture_screenshot_for_script()` and the legacy `capture_screenshot()`. A device that drives
  no page — a TV, an Android box, anything but a browser run — is untouched: it still uses the
  capture folder, and so does a browser run whose page died mid-shot.
- **A browser run on a shared screen takes no image rather than the wrong one.** The executor
  asks for the run's "before" and "after" shots, and a browser run has no page at either moment
  — the first before it launches Chrome, the last after it closes one. Falling back to the
  shared capture there meant the newest capture, which is whichever run was on top. There is no
  honest image at those moments, so there is none, and the run log says why. This is gated on
  the AV controller being a VNC / x11grab capture (a shared display): an HDMI set-top box, whose
  screen belongs to it alone, is unaffected.

Nothing else moved. The host's capture loop keeps photographing the whole screen, which is what
it is for: the device really is displaying two overlapping windows, and monitoring should see
that.

### The two moments with no page, and why the screen is not the answer

The executor's initial and final shots (`shared/src/lib/executors/script_executor.py:2055`) are
device-level: state before the script does anything, and after it finishes. For a browser run
they were the two most prominent images in the report and the two most likely to be wrong —
the initial one is taken while the *other* run's browser is the only thing on `DISPLAY=:1`.

So for a browser run on a shared display they are now **skipped**, with the reason in the run
log. The run's own step images — taken while its browser is alive — carry the evidence, and
they are per-run by construction.

### The first deploy changed nothing, and the run log said why

The first version of this fix wired **only** `capture_screenshot_for_script()`. It deployed
cleanly, the tests passed, and a live run on `host-clone-2` still wrote the shared screen capture
into the report:

```
✅ [youtube_video_check] Screenshot captured: capture_000388253.jpg
```

That message comes from the **legacy** `capture_screenshot()`, which is what the script executor
calls for a run's initial and final artifacts
(`shared/src/lib/executors/script_executor.py:2055`) — the two images in the report header. The
web scripts call `capture_screenshot_for_script()` for their own step ids, which is a different
path entirely.

### The second deploy was also a no-op: the method handed back a coroutine

With the fix moved onto both paths, the run still fell back. This time the log said exactly
what was wrong:

```
📸 [youtube_video_check] Capturing initial state screenshot...
⚠️ Screenshot capture failed: stat: path should be string, bytes, os.PathLike or integer, not coroutine
```

`@ensure_controller_loop` answers **two different ways**. From a plain thread it submits the
coroutine to the controller loop and returns `fut.result()` — the value. But when the caller
already has a running loop it returns `asyncio.wrap_future(fut)`, an **awaitable**. The script
executor calls this from inside a loop, so `capture_page_screenshot(path)` handed back a
coroutine; `os.path.exists(coroutine)` raised; and because that check sat *outside* the caller's
`try`, the error escaped as a capture failure instead of the miss it was.

Three lessons, all now in the code and in the tests:

- the fix goes on **every** path that produces a report image, not the one that was easiest to
  find;
- the method is **not** decorated. It submits `_photo_page` to the controller loop itself and
  blocks on the future with a timeout, so either kind of caller gets a path, and a wedged
  driver cannot stall a run;
- **the fallback says why, and it never leaks a coroutine.**
  `capture_run_page_screenshot()` used to return `None` in silence, which is why two no-op
  deploys looked like working ones. Every miss now prints `📸 [device_utils] No run page
  screenshot (<reason>)`; a device that simply drives no page stays quiet, because that is not
  a miss; and an unusable answer is closed rather than left to warn in the run log.

The two no-op deploys were caught only because the run was actually executed on a host. Both
times the fix had passed its own tests: the tests used a fake controller that returned a path,
and never the decorator that returned a coroutine.

## Verification

### Live, on `host-clone-2`, deploy `main-2026.10.21-89537`

Two web scripts started through the platform API at the same time, on the same host and device —
youtube on port **9300**, dailymotion on port **9301**, each with its own Chrome profile. No
`423`; the dailymotion run took no device lock, so the two really did overlap. The host's own
image list, interleaved:

```
[web/youtube_video_check.py]     --remote-debugging-port=9300
[web/dailymotion_video_check.py] --remote-debugging-port=9301
[youtube]     add_screenshot: 1792613861398290870_youtube_home_state.png
[dailymotion] add_screenshot: 1792613868768707418_dailymotion_home_state.png
[youtube]     add_screenshot: 1792613870129224137_youtube_video_opened.png
[youtube]     add_screenshot: 1792613870781475208_youtube_ad_state.png
[dailymotion] add_screenshot: 1792613872175218037_dailymotion_video_opened.png
[youtube]     add_screenshot: 1792613890972581093_youtube_monitor_end.png
[dailymotion] add_screenshot: 1792613907279278370_dailymotion_monitor_end.png
```

Every step image is the run's own page, taken while its own browser was alive, with a filename
carrying its own run and its own nanosecond stamp. Before the fix all eight would have been the
same two or three `capture_*.jpg` files out of the host's shared capture folder — the newest of
which belongs to whichever window was on top.

`tests/backend_host/test_run_page_screenshot.py` (31 tests):

- a browser run's report image comes from its own page and the screen capture is not called at
  all — **on both paths**, the script one and the legacy executor one;
- a device with no live page, and a device with no web controller, both keep the screen capture;
- a controller that raises, and a browser that died before the shot, both fall back to the
  screen capture instead of raising;
- an awaitable answer is a miss, not a crash, on both paths — the case that made two deploys
  no-ops; and a path with no image behind it is a miss too;
- the controller answers a plain caller with a `str`, never an awaitable; a wedged driver times
  out instead of stalling the run; a missing controller loop is a miss, not a crash;
- a miss prints why, and a device with no web controller stays quiet;
- a browser run on a **shared** screen with no live page takes **no** image, on both paths, and
  says why — the executor's before/after moments have no page by construction, and the shared
  screen would show the other run;
- an **HDMI** device (its screen is its own) still gets its capture, a device that drives no
  browser at all still gets it, and a live page still wins over the skip;
- two runs writing the same `screenshot_id` get two different files, and the file sits under the
  run's own directory; a run with no `VPT_RUN_ID` is isolated by pid;
- the controller creates its directory, photographs the **first** page of the context, never
  opens a page, and returns `None` when there is no browser.

No regression in the suites around it: 108 passed across the browser-isolation tests
(`test_browser_port_allocator.py`, `test_browser_isolated_parallel_runs.py`,
`test_browser_run_slots.py`), the screenshot callers (`test_testcase_background_report.py`,
`test_game2048.py`) and `test_av_check_script.py`.

### The skip, confirmed on a host

The run above was made against the deploy that carried the coroutine fix. The skip came after
it, so it got its own run — same host, same pair, deploy `main-2026.10.21-89537`, host marker
`80da55a2f8a2…` matching the merge exactly:

```
[youtube]      📸 [device_utils] No device shot for this browser run — this host's screen is shared between runs …
[youtube]      ℹ️ [youtube_video_check] Device shot skipped (shared screen, no image of this run)
[youtube]      --remote-debugging-port=9300
[dailymotion]  📸 [device_utils] No device shot for this browser run — this host's screen is shared between runs …
[dailymotion]  ℹ️ [dailymotion_video_check] Device shot skipped (shared screen, no image of this run)
[dailymotion]  --remote-debugging-port=9301
[dailymotion]  add_screenshot: 1792614515374060832_dailymotion_browser_ready.png
[youtube]      add_screenshot: 1792614518368832262_youtube_home_state.png
[dailymotion]  add_screenshot: 1792614525388558670_dailymotion_home_state.png
[youtube]      add_screenshot: 1792614528261852259_youtube_video_opened.png
[youtube]      add_screenshot: 1792614529042193019_youtube_ad_state.png
[dailymotion]  add_screenshot: 1792614529058723699_dailymotion_video_opened.png
[youtube]      add_screenshot: 1792614549310424695_youtube_monitor_end.png
[dailymotion]  add_screenshot: 1792614564161298042_dailymotion_monitor_end.png
```

**Not one `capture_*.jpg` appears in either report.** That file was the shared screen, and it is
gone: every image in both reports is the run's own page, and the two reports share nothing.
# BUG-0114 — A second web script kills the first one's browser mid-run

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                         |
|-----------|-----------------------------------------------------------------------------------------------|
| ID        | BUG-0114                                                                                        |
| Reported  | 2026-09-16                                                                                      |
| Status    | **Fixed (pending deploy).**                                                                     |
| Severity  | High (every web script on a host that runs two of them close together; the victim fails outright) |
| Area      | `backend_host/src/lib/utils/playwright_utils.py`, `backend_host/src/controllers/web/playwright.py` |
| Fixed in  | build 9151                                                                                         |

---

## Symptom

A web script failed at a navigation partway through its run, seemingly at random, on both
`youtube_video_check.py` and `dailymotion_video_check.py`:

```
⏱️ Total Time: 16.2s
📸 Screenshots: 2 captured
🎯 Result: FAILED
❌ Error: Failed to navigate to video: Exception: Page.goto: Connection closed while
   reading from the driver
```

The earlier navigation in the same run — to the site's home page — had already succeeded, and
nothing between the two touches the browser. Reported as intermittent, and as affecting more
than one site, which ruled the sites themselves out.

## Root cause

**`Connection closed while reading from the driver` is Playwright saying its own node driver
process was killed.** It is not a dead browser: a browser that dies under `connect_over_cdp`
reports `Target page, context or browser has been closed`. So something SIGKILLed the driver
mid-run.

That something was our own Chrome launcher. `launch_chrome_with_remote_debugging` cleared the
debug port before launching:

```python
if cls.is_port_in_use(debug_port):
    result = subprocess.run(['lsof', '-ti', f':{debug_port}'], ...)
    for pid in result.stdout.strip().split('\n'):
        subprocess.run(['kill', '-9', pid.strip()])
```

`lsof -i :PORT` matches **any socket with that port on either end**, so it returns the browser
(the listener) *and* every Playwright node driver holding a CDP connection to it. All of them
were killed.

And that path ran on essentially every web script start. Each script runs in its own subprocess
(`ScriptExecutor` launches one per run), so `PlaywrightWebController._chrome_running` — a
class attribute, therefore per-process — is always `False` at startup. `ensure_browser_session`
sees `is_connected == False`, calls `open_browser()` → `connect()` → `launch_chrome()`, and the
kill above fires. The debug port was hardcoded to one value for every device on the host, so
there was nothing to separate two sessions.

The result: **whichever of two overlapping web scripts reaches `launch_chrome` second destroys
the first.** From a host journal, the same collision on every cycle — one script launches its
browser, the next one kills it four seconds later:

```
11:20:19  [web/facebook_check.py]        [@script_executor] Executing: …
11:20:21  [web/facebook_check.py]        [ChromeManager] Launching Chrome with remote debugging
11:20:21  [web/youtube_video_check.py]   [@script_executor] Executing: …
11:20:25  [web/youtube_video_check.py]   [ChromeManager] Port 9222 is in use. Killing processes...
11:20:25  [web/youtube_video_check.py]   [ChromeManager] Killed process … using port 9222
11:20:25  [web/youtube_video_check.py]   [ChromeManager] Launching Chrome with remote debugging
```

Which script fails is just which one lost the race, which is what made it look random. In the
window above `facebook_check.py` was the victim on every single cycle for hours, and nobody had
noticed because attention was on the run that *was* being watched.

## Fix

Two small changes, after a first attempt that was reverted (see the end of this section).

**Never kill a CDP client.** The port-clearing lookup is now `lsof -t -sTCP:LISTEN -i :PORT`,
which can only ever match the browser itself. That one flag is what makes the reported error
impossible: no launch can reach another run's Playwright driver any more.

**Queue behind a running session instead of launching over it.** Every script closes its
browser at teardown (`script_executor.py`, `close_browser(wait=True)`), so a Chrome that is
still answering `GET /json/version` on the debug port when a script starts belongs to a run
that has not finished. `connect()` now waits for it to go away — up to `VPT_WEB_BUSY_WAIT`
seconds, default 300 — and only then launches its own. Past the deadline the browser is an
orphan from a run that died without teardown, and the launcher takes the port exactly as it
always did (killing the listener only). No new state, no lock file: the live browser *is* the
signal.

The same over-broad `lsof` was fixed in the local-debug helper
(`shared/src/lib/utils/local_debug_browser_helpers.py`), which cleared the port the same way.

**What was reverted, and why.** The first fix (`df868be125`, `6692e30afe`) added two more
mechanisms on top: *reuse* a healthy Chrome rather than relaunching, and a host-wide `flock`
so a second session is refused. Review showed the reuse was broken under the very condition it
targeted — the first script owns the Chrome process and kills it at its own teardown, so a
second script that had attached to it died anyway, just with a different message — and the lock
was a second locking system for a problem that belongs to the dispatcher (below). ~250 lines
replaced by ~40.

## Verification

- `lsof -t -sTCP:LISTEN -i :PORT` against a live listener returns the listening PID only — the
  bare form on the same port also returned its connected clients.
- The wait loop, against a stand-in CDP endpoint that serves `/json/version` for a few seconds
  and then stops: the probe reads `True` while it is up, the loop waits, exits once it is gone,
  and the probe reads `False` after.
- End-to-end, the two scripts that collided are run back-to-back on the host where it
  reproduced; the second one's log must show `waiting up to 300s for it to finish` followed by
  `Port freed after Ns`, and both must pass.

## Not fixed here

**Why two web scripts overlap at all.** This is the actual root cause and it is still open.
`/server/script/execute` takes a device lock before dispatching, and the deployment scheduler
has two gates of its own, yet two runs reached the same device seconds apart. The wait added
here makes that harmless; it does not explain it. Tracked separately.

**One browser per host, not per device.** The debug port is a single hardcoded value, so a host
with two web devices runs one web session at a time. Per-device ports plus per-device profile
directories would be the full answer, and would also require keying the controller's
class-level browser state by port.

**A browser opened by hand counts as a running session.** Opening the browser from the UI's Web
panel puts a Chrome on the port with nobody to close it (`releaseControl` does not), so the next
script waits the full 300s and then takes the port over — which closes the manual session. Close
the browser when done.

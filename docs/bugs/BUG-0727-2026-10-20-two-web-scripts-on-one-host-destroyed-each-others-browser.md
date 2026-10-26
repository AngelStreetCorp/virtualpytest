# BUG-0727 — Two web scripts on one host destroyed each other's browser

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0727                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High (a web run fails outright when a second web run starts on the same host) |
| Area      | backend / testing                                            |
| Fixed in  | build 90145 |
| Commit    | 2e74d65e0                                                    |

---

## Symptom

Two web scripts started on the same host at the same time never both succeed. The second one either
refuses to start, or starts and destroys the first one's browser:

```
POST /server/script/execute  → 423 {"errorType":"device_locked","error":"Device <host>:<device> is locked"}
```

and, when the lock is out of the way (the second script started directly on the host), the first run
dies with

```
❌ Error: Video was not playing during 20s monitoring window
```

while the second one reports

```
[PLAYWRIGHT]: Page acquisition failed (TargetClosedError: BrowserContext.new_page:
Target page, context or browser has been closed)
[PLAYWRIGHT]: No existing Chrome found (nothing listens on debug port 9222), launching new Chrome...
[PLAYWRIGHT]: BrowserType.connect_over_cdp: connect ECONNREFUSED ::1:9222
```

and the two runs trade places: sometimes the second run kills the first one's browser, sometimes the
first run's cleanup kills the second one's.

## Root cause

Every browser on a host used **one** debug port and **one** Chrome profile directory, and each run
treated any browser it found on that port as its own.

**One port per host.** `PlaywrightUtils` hard-coded `debug_port=9222`
(`backend_host/src/lib/utils/playwright_utils.py`) and the web controller never overrode it
(`backend_host/src/controllers/web/playwright.py`). Two Chromes cannot both use it, so the second one
had to take it away from the first:

- the launcher **killed** the listener on the port ("Port 9222 has a listener - taking it over",
  `ChromeManager.launch_chrome_with_remote_debugging`), and
- the controller **attached to and reused** the browser that was already there
  (`_claim_chromium` in `backend_host/src/controllers/web/playwright.py`) — two runs then drove the
  **same tab**.

**One profile per host.** `user_data_dir` defaulted to `./config/user_data`, resolved to a single
directory for every browser on the host. Two Chromes can never share a user-data-dir at all: the
second one joins the first through its `SingletonLock`.

**The cleanup was host-wide.** `ChromeManager.shutdown_chrome()` killed our own browser and then
**whatever still listened on the port** — by the time the first run's cleanup ran, the listener was
the *second* run's browser. The local-debug helper did the same: "ANOTHER BROWSER IS ALREADY RUNNING
on CDP port 9222 — killing it" (`shared/src/lib/utils/local_debug_browser_helpers.py`).

**The dispatcher serialized the runs.** `/server/script/execute` takes an exclusive device lock per
`host_name:device_id` (`backend_server/src/routes/server_script_routes.py`), so the second run was
refused with `423 device_locked` and queued as a deployment before it ever reached the browser.

This is the part [BUG-0114](BUG-0114-2026-09-16-a-second-web-script-kills-the-first-ones-browser.md)
left open: "One browser per host, not per device" and "Why two web scripts overlap at all".

## Fix

**A free debug port per run.** A new module, `shared/src/lib/utils/browser_port_allocator.py`, hands
each run a port that is free and reserved in a small per-host registry (guarded by an `flock`), so two
runs starting at the same time never pick the same one, and a reservation whose owner is gone is
pruned. A script run takes a port from **9300+**; **9222 stays reserved** for the host's own service
browser (the agent tree, the web worker and the KPI executor attach to it). `VPT_CHROME_DEBUG_PORT`
pins a port explicitly.

**A profile directory per run.** Two Chromes can never share a user-data-dir, so a run gets
`backend_host/config/user_data_runs/<run id>` — a sibling of the persistent profile, which the host's
own service browser keeps, so its cookies and its logged-in session survive. `VPT_CHROME_PROFILE_DIR`
pins a profile explicitly. The local-debug path gets `/tmp/virtualpytest_<profile>_<run id>`.

**The orphan cleanup only touches its own port.** `launch_chrome_with_remote_debugging()` refuses to
take over a port that a **live** run owns (it takes another free port instead), and
`shutdown_chrome()` kills the listener on the port **only** when no live run owns it: a leftover from
a dead run is still reaped, another run's browser is left alone. The local-debug helper takes a free
port instead of killing the listener.

**Two web scripts no longer queue behind each other.** A web script that drives its own Chrome
declares `"browser_isolated": True` in its `_target_rules`. The server lets such a run go **beside**
another browser-isolated run on the same device instead of refusing it with `423`
(`backend_server/src/routes/server_script_routes.py`). The parallel run holds no lock of its own and
therefore never releases the other run's lock; every other owner — a Take Control, a script that
drives the host's own browser — still blocks the device. The host tracks the running scripts per
device as a list, so two parallel runs on one device are both abortable.

## Verification

- `tests/backend_host/test_browser_port_allocator.py` — two runs never get the same port, the reserved
  port is never handed to a run, a dead run's reservation is pruned, the cleanup leaves a live run's
  browser alone and reaps a leftover, a run gets its own profile while the service browser keeps the
  persistent one.
- `tests/backend_server/test_browser_isolated_parallel_runs.py` — which lock may be run beside, that
  the second run does not release the first run's lock, and that a normal script run still blocks the
  device.
- End to end on a free web host, **before** the fix: the second script was refused with
  `423 device_locked`; started beside it anyway, it attached to the first script's browser and drove the same
  tab, and the first script's cleanup then killed the second script's browser
  (`TargetClosedError` → `ECONNREFUSED :9222`).
- End to end on the same host, **after** the fix: the two web scripts started **23 ms apart** and ran side by
  side — Chrome on **9300** with the profile `config/user_data_runs/<run id A>` and Chrome on **9301** with
  `config/user_data_runs/<run id B>`, both listening at the same time. Neither log contains
  "already on debug port", "taking it over", "browser has been closed", `TargetClosedError` or
  `ECONNREFUSED`; each run terminated only its own browser and freed only its own port, and the host's port
  registry was left with the service browser's 9222 alone.
- The control — the **same** script run alone on the same host — gives the same verdict as the two parallel
  runs ("video playback not confirmed during monitoring window"), so a parallel run behaves exactly like a
  solo run. That remaining verdict is the site's video playback in this lab, a separate defect that fails the
  same way before and after this fix.

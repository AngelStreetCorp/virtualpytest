# BUG-0179 — Every web goto took six minutes: it waited 300 s for an orphan Chromium nobody would ever close

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                         |
|-----------|-----------------------------------------------------------------------------------------------|
| ID        | BUG-0179                                                                                        |
| Reported  | 2026-09-28                                                                                      |
| Status    | Fixed (pending deploy)                                                                          |
| Severity  | High (every web script on the host, once one browser has been left behind; 6 min instead of 50 s) |
| Area      | `backend_host/src/controllers/web/playwright.py`, `backend_host/src/lib/utils/playwright_utils.py` |
| Fixed in  | Unreleased                                                                                      |
| Commit    | `29a289e81`                                                                                     |

---

## Symptom

On host-clone-1 (device `host_vnc`, `youtube-web`), consecutive `goto` runs took ~6 minutes each
instead of ~50 s, all of it spent before the first navigation:

```
[PLAYWRIGHT 09:01:41.123]: Another session's CHROMIUM is on the debug port - waiting up to 300s for it to finish
[PLAYWRIGHT 09:06:42.014]: Still busy after 300s - treating that CHROMIUM as abandoned and taking the port
[PLAYWRIGHT 09:06:49.198]: Browser opened and ready in 308079ms
```

The Chromium on port 9222 belonged to the *previous* goto, which had already completed — the
server had received `task_complete` and released the device lock — but its browser was still up.

## Root cause

Two defects, one on each side of the run.

**The wait itself.** BUG-0114 made `connect()` queue behind a live browser on the debug port for
up to `VPT_WEB_BUSY_WAIT` (300 s) on the theory that "every script closes its browser at teardown,
so a live Chrome means a run is still in progress". That premise is false whenever teardown does
not actually close the browser — and then every later script pays the full 300 s before taking
the port. The device lock (server-side `lockedDevices`) is what guarantees two scripts never drive
the same browser at once, so a browser on the port when a new script holds the lock is by
definition an orphan. Waiting for it can never help.

**Why teardown left it behind.** The 08:42 run's first browser use was a *verification*
(`waitForElementToAppear`), which reaches the browser through `_get_persistent_page()` →
`connect_browser()`: that attaches over CDP to whatever is on the port and never launches. So the
run adopted an earlier orphan, `_chrome_process` stayed `None`, and at teardown
`close_chrome_gracefully(chrome_process=None)` had nothing to terminate. Its "graceful" CDP
shutdown was a `POST /json/runtime/evaluate` — not a Chrome DevTools HTTP endpoint at all — so it
failed on every run (`[ChromeManager] CDP shutdown failed: HTTPConnectionPool(...)`), and the only
real kill was the `Popen.terminate()` fallback, which needs a Popen. One un-closed browser therefore
seeded a chain: attach → cannot kill → next run waits 300 s → kills it and launches its own → …

In the same run, `open_browser` → `connect()` then saw a busy port, waited the 300 s, and killed
the very browser the run had been using since its first verification.

**Who actually holds the port.** Verified on host-clone-1 after the fix: the browser found on
port 9222 at the start of a goto is launched by the **KPI executor service** (`vpt-kpi.service`,
`backend_host/scripts/kpi_executor.py`). It measures web KPIs by running the step's web
verification (`waitForElementToAppear`) through the same `PlaywrightWebController`, attaches to the
script's browser if one is there, and otherwise launches its own — in-process, in the service's
process group, and never closed. So every goto leaves a KPI-owned Chromium behind, and under the
old code the next goto waited the full 300 s for it, then `kill -9`ed it. The KPI service's own
`connect()` carried the same wait, so a KPI job that started while a script's browser was live
would wait 300 s and then kill the script's browser mid-run (BUG-0114's failure, from a third driver
the device lock does not cover).

## Fix

**Never wait.** `connect()` now makes one decision, `_claim_chromium()`:

- port free → launch;
- port busy → attach to the browser over CDP and reuse its first context/page (the same path
  `connect_browser()` already used), bounded by `VPT_WEB_ATTACH_TIMEOUT` (15 s) and a
  `page.evaluate` liveness probe; if it does not answer, kill its process group and launch fresh.

`BROWSER_BUSY_WAIT_SECONDS` / `VPT_WEB_BUSY_WAIT` are gone. An attach from either entry point now
marks the browser as this run's (`_chrome_running = True`), so the other entry point neither attaches
a second time nor launches over it.

**Teardown really closes the browser.** `_cleanup_persistent_browser()` first sends the real CDP
`Browser.close` over the Playwright connection it already holds, then disconnects, then calls
`ChromeManager.shutdown_chrome()`: SIGTERM→SIGKILL on the launched process **group** (Chrome is
now launched with `start_new_session=True`, so its zygote/renderer/gpu helpers go with it), then
on whatever still *listens* on the port (`lsof -t -sTCP:LISTEN`, never a CDP client — BUG-0114),
and it returns only once the port has no listener. A listener that is not a group leader — e.g. a
browser opened from the vpt-host service — is signalled alone so the kill can never reach the
service. The launcher uses the same routine to take the port.

## Verification

- `tests/backend_host/test_playwright_connect_decision.py`: port free → launch; port busy → reuse
  (no sleep at all); port busy but CDP refused / page wedged → kill then launch, bounded by the
  attach timeout; the verification-first chain no longer relaunches; teardown sends `Browser.close`
  and kills through the port even with no Popen; `shutdown_chrome` escalates TERM→KILL on the group
  for a leader and signals a non-leader alone.
- On host-clone-1 after deploy: two `goto --userinterface youtube-web --node home --device host`
  back to back; both must finish in under a minute and `pgrep -af remote-debugging-port=9222`
  must be empty between them.

## Not fixed here

**The KPI executor shares the script's browser and is not covered by the device lock.** A KPI
job for run N can still be scanning the page when run N+1 takes the device, attaches to the same
Chromium and starts navigating; the KPI measurement then reads run N+1's page (and its browser is
killed at run N+1's teardown, which it survives by relaunching). The measurement is already
"scan budget exceeded" on youtube-web. The KPI executor needs its own browser lifecycle — close
after each measurement, or a port of its own — tracked separately.

One browser per host (single hardcoded debug port), and why two web scripts once overlapped at
all — still tracked under BUG-0114's "Not fixed here".

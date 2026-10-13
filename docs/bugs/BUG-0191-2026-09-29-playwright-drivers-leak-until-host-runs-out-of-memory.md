# BUG-0191 — Web hosts ran out of memory after a few hours of tests, because every browser connection left a Playwright driver running

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                          |
|-----------|------------------------------------------------------------------------------------------------|
| ID        | BUG-0191                                                                                       |
| Reported  | 2026-09-29                                                                                     |
| Status    | Fixed (pending deploy)                                                                         |
| Severity  | Critical (a web host stops running tests, then stops answering SSH, until the VM is reset)     |
| Area      | `backend_host/src/controllers/web/playwright.py`, `backend_host/src/lib/utils/playwright_utils.py`, `backend_host/src/lib/utils/webkit_utils.py` |
| Fixed in  | Unreleased                                                                                     |
| Commit    | `048bd9ad1`                                                                                    |

---

## Symptom

A web host (8 GB VM) running an hourly web campaign had every test fail for days, then stopped
answering SSH altogether: TCP port 22 accepted connections but the key exchange never finished.
The VM console showed the kernel's OOM killer taking `chromium` and `python` again and again, and
`systemd-journald` failing to restart. Inside the VM, 150 MB of 8 GB was free and the disk was read
at ~33 MB/s nonstop: the kernel was re-reading program pages it had just evicted.

Each OOM report in the previous boot's kernel log listed the same thing. About **220 processes
named `MainThread`**, owned by the host service user, held **~6.4 GB RSS plus ~600 MB swap**.
Chromium itself held 70–240 MB. The first OOM came ~11 hours after boot, so roughly 20 of them
appeared per hour. Resetting the VM cleared them; they came back as soon as tests ran again.

## Root cause

`MainThread` is Playwright's Node driver. Node 24 gives its main thread that name, and the
bundled `playwright/driver/node` shows up as `MainThread` in `ps`. Every
`async_playwright().start()` spawns one, and it exits only on `playwright.stop()` or when its
parent exits. The web controller runs inside the long-lived `vpt-host` process, so a driver whose
handle is dropped without `stop()` lives until the service restarts: ~30 MB each.

Four paths dropped the handle without stopping it:

1. **Failed CDP attach**: `PlaywrightConnection.connect_to_chrome()` (and the WebKit twin
   `connect_to_webkit()`) started Playwright, then `connect_over_cdp()` failed, and the exception
   left with the only reference. `connect_browser()` tries this attach *before* launching Chrome,
   so a run that starts with no browser on the debug port leaked one driver every time. This was
   the main source.
2. **Dead context**: `_get_persistent_page()` cleared `_browser`/`_context` after a
   `TargetClosedError` but never stopped `_playwright`, then reconnected over it.
3. **Failed verification**: `connect_browser()` overwrote `_playwright` when the cached
   connection failed its check.
4. **Teardown timeout**: `_cleanup_persistent_browser_with_timeout()` cancelled the cleanup
   after 10 s. A slow `browser.close()` on a dead CDP link used up that budget before
   `playwright.stop()` ran. The host log showed `Cleanup timed out` / `Timed out waiting for
   browser cleanup` several times an hour.

Once memory ran out, the OOM killer picked the largest single processes (the running browser and
test script), never the ~220 small drivers, so every later test failed while the leak stayed.

## Fix

- `stop_playwright()` in `playwright_utils.py`: `stop()` bounded to 5 s. If it hangs, the
  driver process is killed through Playwright's pipe transport.
- `connect_to_chrome()` / `connect_to_webkit()` stop the Playwright they started when the attach
  fails, including on cancellation (the attach runs under `asyncio.wait_for`).
- The controller's `_drop_playwright_handles()` stops the driver before forgetting it. It is used
  on the dead-context path, before `connect_browser()` replaces a connection, and when a teardown
  times out.
- Teardown bounds `browser.close()` (3 s) and keeps `_playwright` set until it has stopped, so a
  timeout that cuts it off still leaves something to stop. The cleanup budget is 15 s, and
  `close_browser(wait=True)` waits 22 s.

## Verification

- `tests/backend_host/test_playwright_connect_decision.py`: six new tests. Five fail on the old
  code: failed attach, hanging `stop()`, failed verification, dead context, timed-out cleanup. The
  sixth runs five connect/close cycles and asserts no Playwright is left running.
- Real Playwright, 10 attaches to a closed port: **10 drivers left behind before the fix, 0
  after**.
- On a host: `ps -eo comm | grep -cx MainThread` must stay at 0–1 across campaign runs instead of
  growing every hour.

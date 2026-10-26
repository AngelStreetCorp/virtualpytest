# BUG-0838 — Leaked browsers are detected, counted against the run cap, and never closed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                    |
|-----------|------------------------------------------|
| ID        | BUG-0838                                 |
| Reported  | 2026-10-22                               |
| Status    | Fixed (pending deploy)                   |
| Severity  | Medium                                   |
| Area      | backend_host (playwright_utils, deployment_scheduler) |
| Fixed in  | build 90145 |
| Commit    | TBD                                      |

---

## Symptom

A host slowly stops being able to start browser runs. On `host-clone-2` on 2026-10-22:

```python
>>> browser_run_status()
{'running': 0, 'waiting': 0, 'leaked': 2, 'cap': 4}
>>> leaked_browser_ports()
(9300, 9301)
```

Two browsers holding slots, no run using either. `BrowserSlotPool.acquire` counts leaks against
the cap, so as corpses accumulate the host refuses new browser runs outright — with
`host carries N browser(s) left over from finished runs` — while `running` reads 0 and the host
looks idle. Nothing ever closes them: the count only grows, and each leaked Chromium also holds
its share of the RAM the run cap is derived from.

## Root cause

This is a known, deliberate gap rather than an oversight, which is why it went unnoticed: the
detector exists and the kill was withheld.

`shared/src/lib/utils/browser_run_slots.py` computes `leaked_browser_ports()` — a port in the run
range that is listening and has no live owner — and its own docstring is explicit about the
omission:

> **Read-only. This never kills anything.** Reaping a leaked browser is deliberate work done by
> someone who has looked at the list, and signalling a browser's process group without checking
> what else shares that group took a lab host's SSH down with it on 2026-10-22.

That caution came from a real incident, and the reason it was kept: the only reaping path in the
codebase was opportunistic, inside `ChromeManager.launch_chrome`, which takes over an orphaned
listener when it happens to be allocated that exact port. Since `allocate_debug_port` **skips**
ports that are already listening, a new run is always handed a *fresh* port and never revisits the
corpse. The one code path that could have cleaned up is therefore unreachable in practice, and
nothing else was written.

Meanwhile the host already has every safe primitive it needs, all proven by the incident:
`shutdown_chrome(port)` refuses a port whose owner is a live run, and `_terminate_pid` signals a
process group only when the target leads one, so the `vpt-host` service's group is unreachable.

## Fix

`reap_leaked_browsers()` in `backend_host/src/lib/utils/playwright_utils.py` supplies the missing
trigger, reusing the existing primitives rather than adding new kill logic:

- the ports come from `leaked_browser_ports()`, which only ever scans the run range, so the host's
  service browser on 9222 is never a candidate (re-checked explicitly in the reaper as defence in
  depth);
- each port goes through `ChromeManager.shutdown_chrome(port)`, so a run that starts between the
  scan and the kill still protects itself, and the service process group stays unreachable;
- one bad port does not stop the others, and a detector that cannot run is survivable;
- `VPT_REAP_LEAKED_BROWSERS=0` turns it off, as an operator escape hatch in the same shape as the
  monitoring probe modes.

It is registered in `deployment_scheduler.py` as an APScheduler job (`LEAKED_BROWSER_REAP_SECONDS`,
300 s) beside the orphaned-result sweep, deliberately **not** inside the status read that reports
leaks — the boundary BUG-0760 drew. The wrapper swallows every exception, because a job that
raises is dropped by APScheduler and would silently stop reaping for ever.

## Verification

- `pytest tests/backend_host/test_reap_leaked_browsers.py` — 7 passed, and all 7 fail on the
  pre-fix source.
- Covered: exact ports reaped, 9222 never targeted, delegation to `shutdown_chrome` (so the
  live-owner and process-group rules still apply), the kill switch, one bad port not stopping the
  rest, an unavailable detector, and the job never raising into APScheduler.
- On a host after deploy: `browser_run_status()['leaked']` returns to 0 and the cap is whole
  again.
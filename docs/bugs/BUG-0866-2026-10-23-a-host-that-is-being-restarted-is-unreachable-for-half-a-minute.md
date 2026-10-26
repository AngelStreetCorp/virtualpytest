# BUG-0866 — A host that is being restarted is unreachable for half a minute, and the picture proxy answers 502

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0866                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

A lab host (`vpt-pi1`, a 4-core Raspberry Pi) runs at load 12-17 with 73 % of its CPU in the capture stack, and the
Atlas / stb benchmark gets **HTTP 502** and timeouts when it asks the server for a picture of a set-top box.

The 502 comes from the server's picture proxy: `backend_server/src/routes/server_monitoring_routes.py` fetches
`http://<host>:<port>/host/av/images/screenshot/<file>` from the host with `timeout=30` and turns **any** request
failure into

```json
{"success": false, "error": "Failed to fetch monitoring file: ..."}
```

with status **502**.

The host's own restart made it unreachable for most of a minute:

```
Oct 23 11:22:28  vpt-server.service: Main process exited, code=killed, status=9/KILL
Oct 23 11:22:28  vpt-server.service: Failed with result 'timeout'.
Oct 23 12:18:12  vpt-server.service: Failed with result 'timeout'.
Oct 23 12:27:58  vpt-server.service: Main process exited, code=killed, status=9/KILL
```

## Root cause

**Two exits were longer than the unit's stop timeout.**

**The server** (`vpt-server.service`, `TimeoutStopSec=30`) runs under gunicorn, whose `graceful_timeout` defaults to
**30 s** — exactly the same number. The arbiter was still waiting on a busy worker when systemd gave up on the
cgroup: the unit logged `Failed with result 'timeout'`, the process was SIGKILLed, and the API was gone for the
rest of the restart.

**The host** (`vpt-host.service`, same 30 s) had the same shape of problem one layer down
(`backend_host/src/lib/utils/host_utils.py`):

| Step | Wait | Why it waited |
|------|------|---------------|
| `stop_ping_thread()` | `join(timeout=5)` | the ping thread was usually inside an HTTP call |
| `stop_metrics_thread()` | `join(timeout=5)` | the metrics thread was usually inside an HTTP call |
| `unregister_from_server()` | `requests.post(..., timeout=10)` | the server it called was **itself restarting** — the deploy restarts both |

and it ran **twice**: once from the signal handler and once again from `atexit`. Worst case
**2 x (5 + 5 + 10) = 40 s inside a 30 s budget**. The stops that were measured came out at 0 s, because the ping and
metrics threads were idle at that moment; the risk is real when they are not, and the unregister POST is the worst of
the three — it waits for a server that is being restarted at the same moment.

The same picture on the other side: the Pi was already at 63 % of its 4 cores before any restart (the capture monitor
82 % of a core, the three `ffmpeg` capture streams 78 %), so a 30 s timeout was easily missed by a request that had to
wait behind the capture stack.

## Fix

**On the host** — `backend_host/src/lib/utils/host_utils.py`:

* `cleanup_on_exit()` runs **once** (`_cleanup_done` guard) instead of once from the signal handler and once from
  `atexit`.
* `stop_ping_thread()` and `stop_metrics_thread()` join with **2 s** instead of 5 s.
* `unregister_from_server()` posts with `timeout=(2, 3)` instead of `timeout=10`.

The exit path is now **~7 s** at worst, inside the 30 s budget, so the host stops cleanly
(`Deactivated successfully`) and the 502 window shrinks from ~30 s to a couple of seconds.

**On the server** — the same race existed there: gunicorn's `graceful_timeout` defaulted to **30 s**, the same
number as the unit's `TimeoutStopSec=30`, so the arbiter was still waiting on a busy worker when systemd gave up:

* `backend_server/src/lib/server/gunicorn_app.py`: `graceful_timeout` is now **10 s**.
* `backend_server/src/app.py`: the exit cleanup runs **once** (`_cleanup_done`), not once from the signal path and
  once from `atexit`.
* `backend_server/src/agent/core/manager.py`: `stop_background()` joins its worker thread with **2 s**, not 5 s — it
  runs once per background agent, in the exit path.
* `backend_server/src/routes/server_monitoring_routes.py`: `_fetch_host_file()` retries **once** after 2 s when the
  host refuses the connection. A host in the middle of a restart refuses for a second or two, and that used to be an
  immediate **502**. A *timeout* is not retried: the host answered, and the answer is what it is.

The same change set stops the per-frame log spam that had filled the host's journal (423,000 lines/day from the
subtitle monitor alone, 74 % of every line on the box, which made journald auto-vacuum four days of history away) and
skips the OCR and the Localize matcher when the picture has not changed — see
[TASK-169](../tasks/TASK-169-vpt-pi1-load.md).

## Verification

* `pytest backend_host/scripts/test_capture_path_guards.py` — 16 tests, green (the once-only cleanup, the per-reason
  log throttle, the unchanged-picture reuse, the Localize skip).
* `pytest tests/backend_server/test_host_restart_resilience.py` — 5 tests, green (the retry on a refused connection,
  no retry on a timeout, the once-only server cleanup, the gunicorn timeout inside the unit's budget).
* On the host after the deploy: `systemctl stop vpt-host` ends in `Deactivated successfully` well inside 30 s, and
  `journalctl -u vpt-monitor-subtitle --since "-1h" | wc -l` is in the hundreds instead of the thousands.

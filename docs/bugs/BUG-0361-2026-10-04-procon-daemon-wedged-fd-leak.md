# BUG-0361 — vpt-procon wedged for 2 hours after nxbt ran out of file descriptors

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0361                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host (Nintendo Switch, vpt-procon)                   |
| Fixed in  | build 90145 |
| Commit    | `eeba2b0c9`                                  |

---

## Symptom

On vpt-pi1 the Switch became unusable (`state=disconnected`) and stayed so for 2 hours. `journalctl -u vpt-procon`
showed 16 "controller stopped" lines (TypeError / dbus NoReply), then at 19:12:16 nxbt's manager process died with
`OSError: [Errno 24] Too many open files` (at `os.pipe()`), then `create controller failed: No adapters available`
every 15 s (513 lines). Only `systemctl restart vpt-procon` recovered it.

## Root cause

Every controller re-creation leaks file descriptors inside nxbt's own manager process (`Nxbt._command_manager`,
`nxbt.controllers`), not in the daemon (which held ~15 fds). At the limit the manager died; the daemon kept calling
`create_controller` on a dead manager forever.

## Fix

`backend_host/src/controllers/switch/procon/procon_daemon.py`: `Procon.fatal_reason()` is checked every tick. The daemon
logs one `FATAL: ...` line and exits 1 (systemd `Restart=always` starts it fresh) when the nxbt manager process is
dead, when it holds more than `PROCON_MAX_MANAGER_FDS` (400) fds (restart before the leak kills it), or after 5
consecutive create-controller failures.

## Verification

`pytest tests/backend_host/test_procon_daemon_fatal.py`. On the host: `journalctl -u vpt-procon | grep FATAL` shows the
reason after a restart; `ls /proc/$(pgrep -f nxbt | head -1)/fd | wc -l` stays below 400.

# BUG-0234 — Analyzer worker: its log lines reached the journal only when it restarted

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0234                                                     |
| Reported  | 2026-10-02                                                   |
| Status    | Closed                                                       |
| Severity  | Low — no analysis lost, but Sherlock's log was hours behind or empty |
| Area      | `backend_server/config/services/linux/vpt-discard-scripts.service` |
| Fixed in  | Unreleased                                                   |
| Commit    | `790e21623`                                                  |

---

## Symptom

After Sherlock analysed a script result (row written to `ai_decisions` at 06:18 UTC), `journalctl -u
vpt-discard-scripts` showed no `[Sherlock] Jev shadow …` line for it. The lines for earlier analyses
(03:59, 04:18, 05:18 UTC) all appeared at once, stamped 08:03:55 CEST, the moment the worker was
stopped for a deploy.

## Root cause

The worker logs with `print()`. Under systemd its stdout is a pipe, so Python buffers it in blocks
and only flushes on exit. `vpt-server.service` sets `PYTHONUNBUFFERED=1`; the
`vpt-discard-scripts` unit never did.

## Fix

`Environment=PYTHONUNBUFFERED=1` in the unit template (new installs get it from
`install_server.sh`). The unit on the lab server VM is hand-installed, so the line was added there
too, followed by `daemon-reload` and a restart of `vpt-discard-scripts` only.

## Verification

On the lab server, 2026-10-02 10:07 CEST: after the restart the worker's startup lines
(`[@discard_worker] Starting analyzer worker`, …) appeared in the journal at once, and
`systemctl show vpt-discard-scripts -p Environment` lists `PYTHONUNBUFFERED=1`.
Other installs: add the line to `/etc/systemd/system/vpt-discard-scripts.service`, then
`systemctl daemon-reload && systemctl restart vpt-discard-scripts`.

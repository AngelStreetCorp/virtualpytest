# BUG-0229 — A server deploy left the heatmap and discard workers running old code

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0229                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | deploy                                                       |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On the new **System Service Status** dashboard, and on `/status`, the second backend server's
**Heatmap** read *Running but no frame generated since startup*. The processor was in fact
generating and uploading a heatmap frame every minute.

## Root cause

`update_core.sh --server` copies the new code to the server VM and restarts `vpt-server` only.
The other long-running services that run server code — `vpt-heatmap`, `vpt-discard-incidents`,
`vpt-discard-scripts` — kept running whatever code they were started with. On that server,
`vpt-heatmap` had been running for over three weeks, since before `c0de3654e2` (2026-09-16) made
the processor write `/tmp/heatmap_status.json`, the file `/status` reads to tell whether frames
are produced. The code on disk wrote the file; the process in memory never did. On the main
server the heatmap had been restarted by hand after that change, so it looked fine there.

Hosts did not have this problem: a host deploy already restarts its long-running services
(`AUX_SERVICES`) after `vpt-host`.

## Fix

`setup/proxmox/node/update_core.sh`: new `SERVER_AUX_SERVICES` (`vpt-heatmap`,
`vpt-discard-incidents`, `vpt-discard-scripts`), restarted after `vpt-server` on each server with
the same helper and rule as the host services — only those already active, so a worker that was
switched off stays off, and a failure is reported without aborting the deploy.

## Verification

- `bash -n` on the script; the deploy log lists each server service as restarted or skipped.
- After a `--server` deploy the second server's heatmap writes its status file and reads OK on
  `/status` and the dashboard; a switched-off discard worker stays stopped.

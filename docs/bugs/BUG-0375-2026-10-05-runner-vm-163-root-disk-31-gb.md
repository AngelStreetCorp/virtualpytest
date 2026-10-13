# BUG-0375 — Runner VM 163 root disk (31 GB) refilled to 96 percent during a Docker stack job

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0375 |
| Reported  | 2026-10-05 (daily CI report and coordinator) |
| Status    | Fixed (pending deploy) |
| Severity  | High — disk-full failures return |
| Area      | CI runner VMs |
| Fixed in  | Unreleased |
| Commit    | this commit |

---

## Symptom

Root `/` of runner VM 163 went from 29 % (after the morning cleanup) to 96 % within hours; `ci-runner-retention-check` ran every 15 minutes and logged nothing.

## Root cause

VM 163 has a 31 GB root (164 has 82 GB). One Docker stack job puts about 11 GB of images plus build cache under `/var/lib/docker`, the shared npm cache grew to 5.2 GB inside the 3-day retention window, the journal added 300 MB. While a backlog keeps all three runners busy the retention script never pruned Docker (it only does so when no job runs), and the check was silent when below threshold so it was impossible to see why.

## Fix

Freed 7 GB on 163 (npm cache files older than 12 h, dangling images, build cache older than 1 h, journal to 200 MB: 96 % to 78 %). `ci-runner-retention.sh` on both VMs now (1) prunes dangling images and build cache older than 1 h when the disk is over 80 % even though jobs run (tagged images stay), (2) shortens the cache age to 12 h over the threshold and also covers `/home/jndoye/runners/cache`, (3) logs a line on every threshold check. The npm cache of 163 now lives on the runners disk (`cache=/home/jndoye/runners/cache/npm` in `~/.npmrc`). The Docker data root was not moved: 163's runners disk (40 GB, 18 GB used) cannot take 14 GB of Docker data without crossing 80 %.

## Verification

`journalctl -u ci-runner-retention-check.service` shows a `check ok root=..%` line every 15 minutes; root on 163 stays below 80 % across a Docker stack run. Left for the owner: grow VM 163's root disk (`qm resize`, the Proxmox cluster tools did not answer from the proxmox host) or move Docker to a larger disk.

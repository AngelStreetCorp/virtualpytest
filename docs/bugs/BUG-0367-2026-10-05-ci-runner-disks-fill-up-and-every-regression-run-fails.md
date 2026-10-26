# BUG-0367 — The CI runner disk filled up and every Regression Tests run failed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0367                                                     |
| Reported  | 2026-10-05 (daily CI report: 230 of 238 runs in 24 h failed) |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — CI on main was down                                   |
| Area      | CI runner VMs (self-hosted GitHub Actions runners)           |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

Nearly every `Regression Tests` run failed in its install steps (`Install dependencies`, `setup-node`,
`pip install`) with `ENOSPC: no space left on device`. One runner VM had its root filesystem at 100 %.

## Root cause

Nothing ever deleted what the jobs leave behind. On the affected VM the space went to:

- **Docker layers that no image references** — about 60 GB under `/var/lib/docker/overlay2`, left by
  image builds and pulls in the Docker-stack job (`docker system prune` never reclaims them; only
  3 images were really in use).
- Shared package caches (`~/.npm` 3.6 GB, `~/.cache/pip`), the apt cache (2.3 GB), stale `/tmp`.
- On the other VM: a 2.5 GB journal, the npm cache (5 GB) and 6 GB of unused images.

Per-job workspaces (`_work`, about 5 GB each with `node_modules` and Playwright) and runner `_diag`
logs were also never rotated; they live on a second disk and had room, but only by luck.

## Fix

A retention rotation installed on each runner VM: `/usr/local/bin/ci-runner-retention.sh` plus two
systemd timers. A daily timer runs the full cleanup; a 15-minute timer runs it only when the root or
runner disk is above 80 %. Policy: runners with a live `Runner.Worker` are never touched; idle
runners lose job workspaces, `_temp` and `_diag` logs older than 3 days (and everything but the tool
cache if the runner disk is above 85 %); package caches older than 3 days, `/tmp` older than 3 days,
journal above 500 MB or 7 days, apt cache, and `docker system prune` / `docker builder prune`
(`until=72h`, only while no job runs on the VM). The script logs before/after usage to the journal
and warns when the disk stays above 75 %. The units are hand-installed on the VMs (not deployed by
`update_core.sh`); see the internal CI/CD doc, section "Disk retention".

## Verification

- `systemctl list-timers 'ci-runner-retention*'` shows both timers on each runner VM.
- `journalctl -u ci-runner-retention.service` shows the before/after usage of each run.
- `df -h /` and `df -h /home/<operator>/runners` stay below 80 %.
- A re-run of `Regression Tests` on main gets past the install steps.

## Not covered

Docker layers that no image references are not removed by any docker command. If root stays above
75 % after a run, stop the Docker daemon while no job runs, clear `/var/lib/docker`, and start it
again (images are re-pulled by the next run).

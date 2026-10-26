# BUG-0370 — The Docker stack job wasted 90 s and warned `manifest unknown` pulling images that do not exist

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                |
|-----------|--------------------------------------|
| ID        | BUG-0370                             |
| Reported  | 2026-10-05 (Regression Tests on main stayed red after BUG-0367) |
| Status    | Fixed (pending deploy)               |
| Severity  | Medium — a required CI check was red |
| Area      | CI / Docker stack job                               |
| Fixed in  | build 90145 |
| Commit    | this commit                          |

---

## Symptom

In `Docker stack builds and starts` the pre-pull step printed `Error response from daemon: manifest unknown` five times, three retries in a row, then `image pre-pull failed three times`.

## Root cause

CI launches the stack with `VPT_IMAGE_TAG=local`, so the five VirtualPyTest images (server, host, frontend, minio, minio-mc) are built by `launch.sh`, but `docker compose pull` tried to fetch `ghcr.io/angelstreetcorp/*:local`, which was never published. The step is non-fatal; the job's real failure in those runs was `no space left on device` (BUG-0367).

## Second cause (found in run #1748 once the disk was fixed)

The stack uses fixed container names and ports, but the workflow's concurrency group is per commit, so two
pushes ran two Docker-stack jobs on the same runner VM and each one's cleanup step removed the other's
containers: `Conflict. The container name "/vpt-redis" is already in use`. The job now has its own
`concurrency: group: docker-stack, cancel-in-progress: false` (one stack at a time; a newer pending run replaces an older pending one).

Same run: `Backend deps resolve and import (backend_server)` died with `IncompleteRead(83776 bytes read, 280 more expected)`,
identical byte counts on every run (a truncated cached download written while the disk was full), while `pip install` of the same file
resolves and imports cleanly in a fresh venv (checked locally, `pip check` clean, both backends). The pip HTTP cache on runner VMs 163 and 164 was purged; `requirements.txt` was not changed.

## Fix

The pre-pull now runs `docker compose pull --ignore-buildable`, so it only pre-pulls the third-party images (postgres, redis, grafana), which is what it was for.

## Verification

The step passes first time with no `manifest unknown`; a re-run of `Regression Tests` on main is green for the Docker job.

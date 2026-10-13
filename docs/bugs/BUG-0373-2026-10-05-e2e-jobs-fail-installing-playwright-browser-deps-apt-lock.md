# BUG-0373 — The E2E jobs failed installing the Playwright browser dependencies (apt lock)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0373 |
| Reported  | 2026-10-05 (daily CI check: failed e2e rows in cicd.ci_jobs on runs gh showed green) |
| Status    | Fixed (pending deploy) |
| Severity  | Medium — E2E coverage silently lost |
| Area      | CI / regression workflow |
| Fixed in  | Unreleased |
| Commit    | this commit |

---

## Symptom

`E2E Smoke Tests`, `E2E All Pages` and `E2E Viewport Tests` recorded `failure` in `cicd.ci_jobs` (run #1751, #1748) while GitHub showed the jobs green: `Failed to install browser dependencies`, `Installation process exited with code: 100`, then `browserType.launch: Executable doesn't exist`.

## Root cause

A recording mismatch is not the cause: the e2e test steps are `continue-on-error: true` on purpose (they depend on live services), so a real failure is recorded in the database and the job stays green (the lint and component-test jobs now fail honestly, BUG-0371). The failure itself is real: three runners share each VM, and each job runs `playwright install[-deps] chromium`, which calls `apt-get` as root. Two jobs on one VM collide on the apt lock (`Could not get lock /var/lib/apt/lists/lock`, seen on VM 164), apt exits with 100, and the browser is not usable.

## Fix

Every Playwright install/install-deps call in `regression.yml` now runs under `flock /tmp/ci-apt.lock` (jobs on one VM take turns), and the install on a cache miss retries once after 30 s. The e2e steps keep `continue-on-error`; the e2e jobs are not gated here because a flaky live-service dependency should not block the regression run.

## Verification

On the next runs `E2E Smoke Tests`, `E2E All Pages` and `E2E Viewport Tests` start the browser and record `success` in `cicd.ci_jobs`; `Failed to install browser dependencies` no longer appears in their logs.

# BUG-0368 — The docs path check failed on two references in the standalone install guide

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                |
|-----------|--------------------------------------|
| ID        | BUG-0368                             |
| Reported  | 2026-10-05 (Regression Tests on main stayed red after BUG-0367) |
| Status    | Fixed (pending deploy)               |
| Severity  | Medium — a required CI check was red |
| Area      | CI / docs                               |
| Fixed in  | build 90145 |
| Commit    | this commit                          |

---

## Symptom

Job `Docs reference existing paths` failed: `checked 599 path references in 64 files — 2 missing`.

## Root cause

`docs/get-started/gcp-standalone.md` named `scripts/prebuild.sh` (the file is `frontend/scripts/prebuild.sh`, run from `frontend/`, so the repo-root path never existed) and `setup/docker/docker-compose.gcloud.yml`, a local untracked override file that is deliberately not in the repo. Both were added by the standalone-install docs commits (d40d34de4, b2b8d86b7).

## Fix

The refresh step now says `cd frontend && npm run prebuild` (the package script that runs that file), and the override file is named without a repo-root path ("next to the compose file in `setup/docker`"). The checker is unchanged.

## Verification

`bash scripts/docs/check_paths.sh` prints `0 missing`.

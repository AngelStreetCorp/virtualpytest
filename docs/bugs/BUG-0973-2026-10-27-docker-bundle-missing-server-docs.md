# BUG-0973 — The Docker bundle was missing the docs the server mounts, so no release got its bundle

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                          |
|-----------|--------------------------------|
| ID        | BUG-0973                       |
| Reported  | 2026-10-27                     |
| Status    | Fixed                          |
| Severity  | Medium                         |
| Area      | setup, ci                      |
| Fixed in  | build 90258 |
| Commit    | TBD                            |

---

## Symptom

The `Release artifacts` workflow failed on every release tag since 2026-10-13, at the job
"Standalone bundle stands alone": `backend_server mounts …/vpt-docker-<tag>/docs`. The job stops
before the attach step, so no release carried the `vpt-docker-<tag>.tar.gz` bundle.

## Root cause

`setup/docker/docker-compose.yml` bind-mounts `../../docs` into `vpt-server` at `/app/docs`
(search-docs and video-library read it). The image has no copy of its own (`.dockerignore` drops
`docs/`), and `setup/docker/make_bundle.sh` did not put `docs/` in the bundle, so the mount
pointed outside the extracted bundle.

## Fix

`make_bundle.sh` copies `docs/` into the bundle, without `docs/tasks/` (68 MB, mostly
screenshots), the internal `docs/agent/` and image files: about 29 MB, 8 MB gzipped.

## Verification

Built `make_bundle.sh --tag citest`, extracted it, and ran the workflow's own check
(`docker compose … config`, every bind mount must exist inside the bundle): 24 mounts resolved,
none missing (23 resolved and the docs mount failed before).

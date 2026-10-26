# BUG-0376 — Every push queued a full Regression Tests run and the runners never caught up

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0376 |
| Reported  | 2026-10-05 (28 Regression runs queued on main, six runners busy) |
| Status    | Fixed (pending deploy) |
| Severity  | Medium — results for the latest commit arrived hours late |
| Area      | CI / regression workflow |
| Fixed in  | build 90145 |
| Commit    | this commit |

---

## Symptom

After the disk fix, runs for the newest commit on main sat queued for over an hour behind 28 older runs of superseded commits.

## Root cause

The workflow `concurrency` group ended in `github.sha`, so every push had its own group and `cancel-in-progress: true` never cancelled anything: each push queued a complete run, each about 15 minutes on a runner.

## Fix

The group is now the workflow plus the pull-request number or ref, with no SHA (manual `workflow_dispatch` runs keep a run-id suffix so they never cancel each other). `cancel-in-progress` is `false`: a new push replaces the older *pending* run of the same ref but never cancels the running one (with `true`, pushes every few minutes cancelled every main run before it finished and no run ever completed). The obsolete queued runs on main were cancelled by hand once.

## Verification

Push three times while a run is in progress: the running run finishes, the middle pending run shows `cancelled`, the last one runs next.

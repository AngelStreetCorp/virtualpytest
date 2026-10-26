# BUG-0641 — A vpt-host restart kills running scripts and leaves only a placeholder result

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0641 |
| Reported  | 2026-10-18 |
| Status    | Open (platform gap, found in TASK-133) |
| Severity  | Medium |
| Area      | deploy / backend_host |
| Fixed in  | — |
| Commit    | — |

---

## Symptom

A `validation` run on stb3/stb4 (vpt-pi1) and stbv1+ (vpt-mf1) died after 16–40 min with no report. The
`script_results` row stayed a placeholder (`started_at == completed_at`, no `execution_time_ms`), the server
answered `Task not found`.

## Root cause

`update_core.sh` restarts `vpt-host` (and `vpt-server`) when the code changed. The scripts are children of
`vpt-host`, so the restart kills them. The deploy checks leases, not running scripts: a run started through
`POST /server/script/execute` without a device lease is invisible to it. Seen 2026-10-18 on vpt-mf1 (17:07 UTC)
and vpt-pi1 (18:56 UTC). A `vpt-server` restart alone does not kill the run; it only drops the status
registry (see BUG-0633).

## Workaround

Hold a device lease for the whole run (`vpt-lease claim node1-vpt <host>/<device>`), release it when the run ends.

## Fix (not done)

Make the deploy refuse (or wait) while a script runs on the host, or start scripts outside the `vpt-host` cgroup.

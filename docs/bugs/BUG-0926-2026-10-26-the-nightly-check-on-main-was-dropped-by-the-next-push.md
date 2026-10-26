# BUG-0926 — The nightly check on main was dropped by the next push

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0926                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | CI / regression suite                                        |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/ci-nightly-schedule-group`                   |

---

## Symptom

The regression suite that is supposed to run **once a day on `main`** almost never ran. Measured on
2026-10-26 over the last 100 runs of the workflow (back to 2026-10-24 12:51):

```
{'push': 99, 'schedule': 1}
```

The one scheduled run that survived was created at **04:32:20** for a cron of **00:07** — four hours and
twenty-five minutes late — and it passed. Every other night, the scheduled run was dropped before it
started.

The first nightly run that really executed the suite found a red gate on `main` (a type error in the
Virtual Scripts page, BUG-0924) that had been sitting in the tree the whole time. A daily check that
does not run cannot catch anything.

## Root cause

**The nightly run shared the push group's queue, and GitHub keeps only the newest pending run per
group.**

The workflow's concurrency group gave `workflow_dispatch` a run-id-unique group of its own, but not the
`schedule` event, so the nightly run landed in the same group as every push to `main`
([.github/workflows/regression.yml](../../../.github/workflows/regression.yml)):

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}${{ github.event_name == 'workflow_dispatch' && format('-{0}', github.run_id) || '' }}
```

`cancel-in-progress` is `false`, so a running run is never cancelled. But GitHub keeps **the running
run and only the newest pending one per group**, and older pending runs are dropped. `main` gets a push
every few minutes, so the nightly run was still pending when the next push arrived, and the push became
the newest pending run of the group: the nightly one was dropped. The workflow's own comment says what
the cron is for — *"This cron is what guarantees a full regression of whatever main is at 00:07, whether
or not anyone pushed overnight"* — and that guarantee did not hold on a busy day.

## Fix

The nightly run gets its own group, exactly like a manual dispatch:

```yaml
group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}${{ (github.event_name == 'workflow_dispatch' || github.event_name == 'schedule') && format('-{0}', github.run_id) || '' }}
```

A push to `main` can no longer drop the nightly run, and the nightly run can no longer be dropped by
another nightly run. The suite still runs inside the 00:00-07:00 UTC night window, so the runners are
used at the same time as before.

## Verification

- Before: 1 `schedule` run in the last 100 workflow runs (2026-10-24 12:51 → 2026-10-26).
- The workflow file parses and the group expression is the one the manual-dispatch case already used.
- The next nightly window (00:07 UTC) runs the suite on `main` whatever the pushes do.

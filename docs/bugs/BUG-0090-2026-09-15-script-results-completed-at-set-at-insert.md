# BUG-0090 — A running script is indistinguishable from one that failed instantly

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0090                                                                    |
| Reported  | 2026-09-15                                                                  |
| Status    | Investigated and documented; NOT fixed (the fix changes a column contract every dashboard reads) |
| Severity  | Medium (in-flight runs are counted as completed failures in every consumer)   |
| Area      | `shared/src/lib/database/script_results_db.py` · Grafana dashboards reading `script_results` |

---

## Symptom

While a script is running, its `script_results` row reads exactly like a run that
failed instantly:

```
success = false, started_at = T, completed_at = T   (duration 0s)
```

Only when the run finishes does the row flip to its real values. During a 72-second
web script, every query in between reports a 0-second failure.

## Root cause

`record_script_execution_start` writes both fields at INSERT
(`script_results_db.py:40-42`):

```python
'success': False,            # Will be updated on completion
'started_at':   now(),
'completed_at': now(),       # Temporary, will be updated
```

The comments say "will be updated", but nothing marks the row as *in progress*.
`completed_at IS NOT NULL` is therefore true from the moment the run starts, so it
cannot be used to test whether a run has finished — and `success = false` is the
default rather than a verdict.

## Impact

- **Any consumer** that filters `completed_at IS NOT NULL`, or counts
  `success = false`, counts every in-flight run as a completed failure.
- The dashboards already carry a workaround for it — `all-zapping-events.json` has
  `CASE WHEN completed_at - started_at < '1 minute'::interval THEN started_at …`,
  which is a symptom of exactly this.
- It cost real debugging time: during this session three separate runs
  (`ookla_speedtest`, `dailymotion_video_check` on host-clone-1, and
  `dailymotion_video_check` on labox-web) were each read as instant failures while
  they were simply still running. All three had in fact passed.

## Recommended fix

Leave `completed_at` **NULL** until completion, and make `success` nullable
(NULL = still running, true/false = verdict). That makes "is it finished?" a real
question the data can answer, and lets a dashboard show *running* as its own state
instead of inferring it from a duration heuristic.

This is not a drop-in change: several dashboards do arithmetic on `completed_at`
(`LEAST(completed_at, $__timeTo())` in `device-occupancy.json`, `completed_at -
started_at` elsewhere) and would need `COALESCE(completed_at, now())`. Migration +
dashboard sweep should land together, which is why it is written up rather than
patched here.

Interim guidance for anything querying this table: treat a row whose
`completed_at = started_at` **and** which has no `html_report_r2_url` as still
running, not as a failure.

## Related

[BUG-0089](BUG-0089-2026-09-15-virtual-script-materialize-failure-reported-as-success.md)
— the other half of the same theme: run status that reports green (or red) without
evidence. Both come down to the platform not distinguishing "no result yet" from
"a result of false".

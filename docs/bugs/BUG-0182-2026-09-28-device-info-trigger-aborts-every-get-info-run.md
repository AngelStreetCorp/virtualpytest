# BUG-0182 — Every device info run vanished: the new trigger aborted the database record it was meant to observe

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0182                                                     |
| Reported  | 2026-09-28                                                   |
| Status    | Fixed (applied to node1 + QualiAI)                           |
| Severity  | **High** — runs executed but were never recorded; data lost   |
| Area      | db / device info / test execution                            |
| Fixed in  | build 90145 |
| Commit    | `9fba11247`                                                  |

---

## Symptom

Reported as: *"I ran `device_get_info` on vpt-pi1 / stb4, I see it in progress, then no report and
no logs on Run Tests."* The report **was** visible on `/test-results/reports`, which made it look
like a frontend problem.

It was not. Between the moment `20260928a` was applied to the database (~11:00 UTC) and the
hotfix, **every** `get_info` / `device_get_info` run failed to record at all:

- `0` rows written to `script_results` in that window
- `3 of 3` `deployment_executions` left with a NULL `script_result_id`

The runs themselves executed normally and uploaded their reports to R2 — only the database record
was lost.

## The log line

`vpt-host` on vpt-pi1:

```
Sep 28 12:33:11 raspberrypi [device_get_info.py]
  [@db:script_results:record_script_execution_start] Error:
  {'message': 'null value in column "info" of relation "device_info_latest" violates not-null constraint',
   'code': '23502',
   'details': 'Failing row contains (7fdeb4bb-…, stb4, vpt-pi1, 8726d884-…, stb_tv,
               2026-09-28 12:33:10.100416+00, null, null, null, null, null, …)'}
```

## Root cause

`device_info_track()` (TASK-29) fires on the **start** record that
`record_script_execution_start` inserts — a row whose `metadata` carries only
trigger/parameters/versions, with **no `info` key**. Its guard read:

```sql
IF ... OR jsonb_typeof(NEW.metadata->'info') <> 'object' THEN RETURN NEW; END IF;
```

035 expressed the same rule as `WHERE jsonb_typeof(metadata->'info') = 'object'`, where a NULL
excludes the row. Negated inside an `IF`, three-valued logic breaks it:

| expression | value |
|---|---|
| `NEW.metadata->'info'` (key absent) | NULL |
| `jsonb_typeof(NULL)` | NULL |
| `NULL <> 'object'` | **NULL**, not TRUE |
| `false OR false OR … OR NULL` | NULL |
| `IF NULL THEN` | not taken |

So it fell through to the INSERT with `info = NULL`, the NOT NULL constraint raised 23502, and —
because a trigger runs in the caller's transaction — **that aborted the `script_results` INSERT**.

## Why it reached the user as "no report link"

1. No `script_results` row →
2. the script never printed its `SCRIPT_RESULT_ID:` marker →
3. `deployment_scheduler` scrapes that marker from stdout to fill
   `deployment_executions.script_result_id` (`backend_host/src/services/deployment_scheduler.py:1538-1543`)
   → left NULL →
4. Run Tests builds its history from `deployment_executions` and resolves the report and logs URLs
   through that link (`frontend/src/pages/RunTests.tsx:613-614`) → nothing to render.

`/test-results/reports` reads `script_results` directly, so runs from **before** the migration
still showed their reports there — which is what made it look like a UI bug.

## Fix — `20260928c_fix_device_info_track_null_guard.sql`

1. `COALESCE(NEW.script_name,'')` + `jsonb_typeof(...) IS DISTINCT FROM 'object'` make the guard
   NULL-safe.
2. The upsert is wrapped in `EXCEPTION WHEN others → RAISE WARNING`. `device_info_latest` is a
   **derived cache** of `script_results`: losing a row costs one device's info panel until its next
   scan, whereas aborting the caller loses the test run itself. It must never be able to do the
   latter. This wrapper would have contained the incident regardless of the guard, and is the more
   important half of the fix.

## Why the original tests missed it

TASK-29 §3 case 4 was written as "`metadata->'info'` absent **or** not an object" but only
exercised `'{"info":"not-an-object"}'` — a string, so `jsonb_typeof` returns `'string'` and the
`<>` comparison is a clean TRUE. The absent-key case, the only one that yields NULL, was never
run. "All 7 trigger cases green" was true and still missed the defect.

The regression set now covers, explicitly: `info` absent, `metadata` NULL, `info` not an object,
the completion UPDATE, and the views seeing the result. Green on node1 and QualiAI.

## Not recoverable

Runs between ~11:00 and 12:40 UTC on 2026-09-28 have no `script_results` row and cannot be
reconstructed from the database. Their HTML reports and logs are still in R2 under
`script-reports/…` / `script-logs/…` if a specific run is needed.

## Related

- Introduced by [[TASK-29-device-info-latest-table]] (§8 records the same analysis).
- `gw_info_track()` (046) is **not** affected — its `auth_success = 'true'` test is a strict
  equality, so NULL yields false and no insert is attempted. It is unwrapped, though; the
  "a cache must not break its source" argument applies there too and is worth a follow-up.

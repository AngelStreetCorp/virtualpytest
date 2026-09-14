# BUG-0063 — Run Tests list fails when the optional `virtual_scripts` table is absent

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0063                                                                    |
| Reported  | 2026-09-08                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High for a customer deployment with `virtual-scripts` disabled (Run Tests unusable) |
| Area      | shared/src/lib/database/virtual_scripts_db.py · backend_server/src/routes/server_executable_routes.py |
| Fixed in  | build 8713                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

Found while preparing the first customer package (TASK-13): the package disables the
`virtual-scripts` feature (`DISABLED_FEATURES=…,virtual-scripts`), and the customer database
never received the virtual-script migrations (`20260626`, `20260904`, `20260907c`). On such a
deployment the Run Tests page's executables list (`GET /server/executable/list`) would answer
500 — the whole list, disk scripts and test cases included — because PostgREST rejects the
query with `relation "public.virtual_scripts" does not exist` (or `column … does not exist`
when the table exists but lacks `environment` / `folder_id` / `prod_version`).

Reproduced without a database by stubbing the client to raise on `table('virtual_scripts')`:
before the fix the exception propagated out of `list_virtual_scripts()`.

## Root cause

`list_executables()` calls `list_virtual_scripts(team_id)` unconditionally (it merges the DB
scripts into the same list as disk scripts and test cases, TASK-07/TASK-11), and
`list_virtual_scripts()` had no error handling. The *feature* is optional
(`features/virtual-scripts`, not deployed when disabled) but the *core* route still assumed
its table — an optional feature's schema had become a hard core dependency.

## Fix

`list_virtual_scripts()` catches the query failure, logs one warning line
(`[@virtual_scripts_db] ⚠️ virtual_scripts unavailable, listing none: …`) and returns `[]`,
so a deployment without the virtual-script schema simply lists no virtual scripts. The
other helpers (get/create/update/promote) are only reached from the virtual-scripts
feature or from a run that already carries a `virtual_script_id`, so they are unchanged.

## Verification

- Stubbed client raising on `table('virtual_scripts')` → `list_virtual_scripts('t')`
  returns `[]` and logs the warning (this session).
- `python -m py_compile` on the module.
- Live deployments (table present) are unaffected: the query path is identical.

## Follow-up

The three virtual-script migrations stay **recommended** for any customer that may enable
the feature later; they are additive and safe to apply ahead of time (TASK-13 §DB).

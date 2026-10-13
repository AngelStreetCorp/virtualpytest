# BUG-0393 — Script logs printed device-farm keys

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0393                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Closed                                                       |
| Severity  | High                                                         |
| Area      | backend / security                                           |
| Fixed in  | Unreleased |
| Commit    | `TBD`                                                        |

---

## Symptom

Every script's Execution Logs started with lines like
`[@app_utils:load_environment_variables]   DEVICE3_FARM_KEY=<value>`, one per environment variable
whose name contains `DEVICE`, with its value. On a host with cloud-farm devices this printed the
farm access keys, user names and app ids (`DEVICEn_FARM_KEY`, `DEVICEn_FARM_USER`,
`DEVICEn_FARM_APP`). The logs are uploaded with the report and linked from it ("Execution Logs",
and "Logs" on a campaign report), so anyone with a report link could read the keys. Seen on a
campaign run on host-clone-1, 2026-10-04.

## Root cause

`load_environment_variables()` in `shared/src/lib/utils/app_utils.py` ended with a debug loop
printing `{var}={os.environ.get(var)}` for every `DEVICE*` variable. Every script and campaign
run calls it, and its stdout is captured into the run's log.

## Fix

The loop now prints one line with the variable **names** only, never their values
(`shared/src/lib/utils/app_utils.py`). A sweep of `print(... os.environ.get / os.getenv ...)` in
`shared/`, `backend_host/` and `backend_server/` found no other secret value printed.

## Follow-ups (owner)

- Rotate the BrowserStack and Sauce Labs keys: logs uploaded before the fix contain them.
- Decide whether to purge stored execution logs from before the fix.

## Verification

Run any script on a host with `DEVICEn_FARM_*` set and open its Execution Logs: the
`load_environment_variables` line lists names such as `DEVICE3_FARM_KEY` with no `=` value.

### Live check (2026-10-05, node1)

Run of `smoke_goto_live` on host-clone-1 (which has DEVICE3/4_FARM_* set): the uploaded execution.txt has one line `Device configuration variables set: DEVICE2_MODEL, ..., DEVICE3_FARM_KEY, DEVICE3_FARM_USER, ...` with names only; `grep -E 'DEVICE[0-9]+_FARM_[A-Z]+='` finds 0 matches.

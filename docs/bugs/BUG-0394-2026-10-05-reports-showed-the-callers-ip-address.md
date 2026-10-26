# BUG-0394 — Reports showed the caller's IP address

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0394                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Closed                                                       |
| Severity  | Medium                                                       |
| Area      | backend / reports / privacy                                  |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

Every script and testcase report showed who launched it as `Trigger: type=… | ip=<public IP>`:
in the execution log banner, the verification review pack, and the HTML report header. Anyone
with a report link saw the caller's public IP address.

## Root cause

The trigger provenance (`type`, `caller_user`, `caller_ip`) is stored for audit, and three
renderers printed all of it:
`shared/src/lib/executors/script_executor.py` (log banner and review pack),
`backend_host/src/services/testcase/testcase_executor.py` (log banner) and
`shared/src/lib/utils/report_generation_utils.py` (HTML header).

## Fix

The three renderers no longer print `caller_ip`. It is still stored in the result metadata in
the database, and the in-app Test Reports page (signed-in users only) still shows it.

## Verification

Run a script through the API and open its report: the header and log show
`Trigger: type=api | user=…` with no `ip=`; the script result's `metadata.trigger.caller_ip` is
still filled.

### Live check (2026-10-05, node1)

Same run: report header shows `Trigger: type api`, no IPv4 anywhere in report.html or execution.txt; host journal line `[@script_executor] TRIGGER: type=api` with no `ip=`; script result `metadata.trigger.caller_ip` is still stored.

# BUG-0791 — In "All servers" mode the Run page lists the same host three times with nothing to tell the rows apart

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0791                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding TESTER-05, in `docs/tasks/QA-TESTER-findings.md`); reproduced against the live app.

- **Page / route:** /run/tests
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open Test > Run Tests.
2. In the server picker choose "All servers".
3. Read the target list.

**Expected:** One row per host, or a column that says which server each row belongs to.

**Actual:** Three identical `host-clone-1` rows and three identical `host-clone-2` rows (name column and host column the same text in every row), with no server column. A user cannot choose between them.

Evidence:

- [tester-05-all-servers-duplicate-hosts.png](../tasks/qa-evidence/tester/tester-05-all-servers-duplicate-hosts.png)

Related bugs: BUG-0613, BUG-0631.

## Root cause

Same root as BUG-0771 (Status page duplicate): the host is registered on more than one server. See also BUG-0613 and BUG-0631 (All-servers mode).

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

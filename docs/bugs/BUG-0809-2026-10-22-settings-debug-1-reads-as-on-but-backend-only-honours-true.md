# BUG-0809 — Settings shows DEBUG=1 as if debug were on, but the backend only honours DEBUG=true, so debug mode is off

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0809                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Low                                                       |
| Area      | backend / configuration                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-04, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /configuration/settings (tab Server)
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open Settings, tab Server and read `DEBUG` under "Other settings".

**Expected:** A value the server acts on, so an operator can tell whether verbose logging is on.

**Actual:** The field shows `1`. `backend_server/src/app.py:610` reads `os.getenv('DEBUG','false').lower() == 'true'`, so `1` is off. Not an exposure (the Werkzeug debugger stays off); a misleading setting. Accept the same truthy spellings or normalise the stored value.

Evidence:

- [ops-03-settings-environment-development.png](../tasks/qa-evidence/ops/ops-03-settings-environment-development.png)

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

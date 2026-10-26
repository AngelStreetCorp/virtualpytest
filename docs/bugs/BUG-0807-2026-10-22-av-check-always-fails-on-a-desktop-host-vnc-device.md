# BUG-0807 — av_check always fails on a desktop (host_vnc) device because its navigation step looks for a UI tree named after the device model

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0807                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | backend_host / scripts                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding CHAOS-12, in `docs/tasks/QA-CHAOS-findings.md`); reproduced against the live app.

- **Page / route:** a run from /test-execution/run-tests on a host_vnc device
- **Viewport / theme:** n/a (API-driven run)

Steps to reproduce:

1. Target host-clone-1 (model `host_vnc`) and run the `av_check` script (Run page, or `POST /server/campaigns/execute` with the same payload).
2. Read the result after about 3 seconds.

**Expected:** The AV check runs on its own merits, or skips navigation on a desktop device.

**Actual:** `success = false` with `Navigation tree loading failed: User interface 'host_vnc' not found (mode=dev)`. Reproduced twice identically. The OPS run of `av_check` on labox-backend failed the same way in 3 s with a different interface name (`example_mobile`) and was judged a script configuration problem; both point at the same navigation step. The run -> result -> report -> logs chain itself worked (report 200, logs 200).

Evidence:

- [verify-run-3-done.jpg](../tasks/qa-evidence/chaos/verify-run-3-done.jpg)
- [verify-run-5-runpage.jpg](../tasks/qa-evidence/chaos/verify-run-5-runpage.jpg)

## Root cause

`test_scripts/av_check.py:149` `can_navigate(device)` is true for a desktop controller, `:692` calls `load_navigation_tree(args.userinterface, ...)`; `backend_host/src/services/navigation/navigation_executor.py:3528-3531` defaults to mode `dev` and looks up the device model as the UI name.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

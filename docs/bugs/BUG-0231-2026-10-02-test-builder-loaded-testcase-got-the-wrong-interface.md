# BUG-0231 — Test Builder: a testcase opened before a device was picked switched to the device's first interface

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0231                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed — deployed and verified 2026-10-02                     |
| Severity  | Medium — the testcase's navigation blocks are checked and run against the wrong tree until the user notices and picks the interface again |
| Area      | `frontend/src/hooks/pages/useTestCaseBuilderPage.ts` |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

`/builder/test-builder?testcase=f38ad30c…` (a `sauce-demo` testcase, from Test Prompt's "Open in
Test Builder") opened the graph. Picking the device host-clone-1 then set the Interface to
`web_tv`, the device's first compatible interface, instead of `sauce-demo`. Found in the TASK-36
browser check, 2026-10-01. It is the same pattern as BUG-0216 on the Test Prompt page.

## Root cause

The compatible-interfaces effect ran while no device was selected (the testcase loads first)
and its no-device branch cleared `userinterfaceName`. That wiped the name `loadTestCase` had just
set. When the device was picked, the effect found no current interface and took the device's
first compatible one.

## Fix

The no-device branch keeps `userinterfaceName` and only clears the compatible list. A device
that cannot use the interface still falls back to its first compatible one. A superseded
effect run is cancelled after `getAllUserInterfaces()` returns.

## Verification

- `tsc --noEmit` passes.
- After the frontend deploy (Playwright, 2026-10-02): `?testcase=15a89113…` (`sauce-demo`) opened
  with Interface `sauce-demo`. After picking host-clone-1 it stayed `sauce-demo` for 8 s (before the
  fix it became `web_tv`).

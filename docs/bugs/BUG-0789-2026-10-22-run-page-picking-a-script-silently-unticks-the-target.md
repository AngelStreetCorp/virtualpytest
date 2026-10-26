# BUG-0789 — On the Run page, picking a script after a host-level target silently un-ticks the target and leaves Run disabled

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0789                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-19, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /test-execution/run-tests
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open the Run page and tick the target `labox-backend` (panel reads "1 selected").
2. Click the script "Av Check".
3. Look at the target panel again.

**Expected:** The target stays ticked and Run becomes available, or the page says why the target was dropped.

**Actual:** The target un-ticks itself, the counter returns to "0 selected", Run stays greyed out and nothing is said. Picking script first, then target, works (Run enabled). The panels also filter in opposite directions: a target narrows the script list (39 to 21), a script prunes the target selection.

Evidence:

- [ops-19-run-page-target-cleared.png](../tasks/qa-evidence/ops/ops-19-run-page-target-cleared.png)

## Root cause

The Run page filters in two directions, and the two disagreed with each other.

**"Which scripts can I run on this target?"** — `isExecutableCompatibleWithCurrentSelection()` (`frontend/src/pages/RunTests.tsx:1497`) reads a script's rules as `item.target_rules || { target_type: 'all', … }`: a script that declares **no** rules is compatible with every target.

**"Which targets can this script run on?"** — `selectedExecutableRules` (`frontend/src/pages/RunTests.tsx:1142`) read the same script's rules as `selectedExecutable?.target_rules || { target_type: 'device', … }`: the same script, defaulted to **'device'**.

`isTargetKeyCompatibleWithRules()` (`frontend/src/utils/targetCompatibility.ts:128-134`) rejects a host-level target (the `host` pseudo-device, `device_model: host_vnc`) when the rules say `target_type: 'device'`. `labox-backend`'s only device *is* that pseudo-device, so picking any rule-less script dropped the ticked target — the panel went back to "0 selected", Run stayed greyed out, and nothing said why. That is the "the panels filter in opposite directions" the sweep saw.

The 'device' default had nothing behind it: **the server only checks the rules a script actually declares** (`backend_server/src/routes/server_script_routes.py:699-709` — `target_incompatibility()` runs only when `extract_script_target_rules()` found rules), so the server would have run that script on the host target happily. `docs/tasks/TASK-61-virtual-scripts.md` records the same understanding: "host-clone-1/host … was the target for everything that targets host_vnc, the device-model 'all', **or no `_target_rules`**".

A second effect made the drop unconditional: the "normalize the selected target key shape" effect dropped any key whose device id reads `host`, decided on the string alone, whatever the rules said (`RunTests.tsx:1562-1567`). The device id `host` is the host_vnc pseudo-device — the browser device the target list offers like any other device — not "the host". What the guard was really written for is a host selection on a host that has no such device ("Host created with 0 devices").

## Fix

Both directions of the page now read the rules through ONE helper, so they can no longer answer differently.

- `frontend/src/utils/targetCompatibility.ts` — `NO_DECLARED_RULES` (`target_type: 'all'`): the rules of an executable that declares none. It is the shared default the list and the pruning both use.
- `frontend/src/utils/targetCompatibility.ts` — `effectiveTargetRules(rules)`: the ONE entry point that answers "what are the rules of this executable". No rules at all — or an empty rule object, which the server also reads as no rules (`extract_script_target_rules()` returns None for an empty dict) — means `target_type: 'all'`; a declared rule is normalised, so a partial rule reads exactly like the backend reads it (`normalize_target_rules`: a missing target_type means 'device', a missing model means 'all').
- `frontend/src/utils/targetCompatibility.ts` — `hostHasDeviceWithId(host, deviceId)`: tells the host_vnc pseudo-device apart from "the host".
- `frontend/src/pages/RunTests.tsx` — `selectedExecutableRules`, the campaign selector item and the executable-list filter all use `effectiveTargetRules()`, so the page and the server agree in both directions.
- `frontend/src/pages/RunTests.tsx` — the "normalize the selected target key shape" effect no longer drops a target on the device-id string alone: the key stays when the host really has a device with that id, and the rules decide the rest.
- `frontend/src/pages/RunTests.tsx` — when a target *is* dropped (a script that really does declare `target_type: 'device'`, run on a host that has only the host pseudo-device), the page now says so: a warning toast names the script and says the target was removed. The silent un-tick is gone either way.

## Verification

Two regression test files, both on the merged implementation:

`tests/frontend/targetCompatibility.test.ts` (main's suite, 11 tests) — a script that declares no rules fits a host-level (host_vnc) target and a real device target; a device-typed script does not fit a host-level target, a host-typed script fits a host-level target on a host that has the browser device and does not fit one that has not; `hostHasDeviceWithId` is true for the host_vnc pseudo-device and for a real device, false for an unknown device and an unknown host.

`tests/frontend/targetCompatibilityRules.test.ts` (7 tests) — `effectiveTargetRules(undefined)` and `effectiveTargetRules(null)` are `NO_DECLARED_RULES`; `effectiveTargetRules({})` is `NO_DECLARED_RULES` too (an empty rule object is no rules, as on the server); a partial rule `{ host_os: 'linux' }` normalises to device / linux / all, the way `normalize_target_rules()` does; a declared rule is kept as it is; a rule-less executable fits the host_vnc pseudo-device.

With the source reverted, the new assertions fail; with the fix all of them pass, and the existing `RunTests` page test still passes. `tsc --noEmit` is clean.


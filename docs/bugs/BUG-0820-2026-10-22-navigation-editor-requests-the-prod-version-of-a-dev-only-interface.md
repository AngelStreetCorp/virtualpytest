# BUG-0820 — The navigation editor also requests the prod version of a dev-only interface and gets a 404 on every open

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0820                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Low                                                       |
| Area      | frontend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding CHAOS-11, in `docs/tasks/QA-CHAOS-findings.md`); reproduced against the live app.

- **Page / route:** /navigation-editor/<interface>
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open `/configuration/interface` and click an interface that exists only in dev, for example `stb3_autobuild`.
2. Check the console and network.

**Expected:** The editor asks only for the version it edits.

**Actual:** The tree renders (18/18 nodes) but `GET /server/userinterface/getUserInterfaceByName/stb3_autobuild?mode=prod` answers `404 {"error":"User interface not found"}`; `mode=dev` answers 200. The user sees nothing; the console and the server log carry an error for a request that cannot succeed.

Evidence:

- [walk-p5-chaos-p5-2026-10-22-s0199.jpg](../tasks/qa-evidence/chaos/walk-p5-chaos-p5-2026-10-22-s0199.jpg)

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

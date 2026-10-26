# BUG-0804 — The Localize "Close calls" tile reads 0 while the table below lists two, and the table ignores the time window

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0804                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-05, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /monitoring/localize (Live results)
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. Open Localize > Live results.
2. Read the Close calls tile, then scroll to "Close calls to check".
3. Switch the window to 1 h.

**Expected:** Tile and table count the same thing and follow the window.

**Actual:** Tile: "0 of 0 named" (and Total runs 0, Active devices 0); table: two close calls dated 18 and 19 October that stay when the window changes. The tile reads `summary.uncertain` for the selected window; the table is an un-windowed backlog. Both rows say "Screenshot no longer on the host".

Evidence:

- [localize.png](../tasks/qa-evidence/analyst/pass1/localize.png)

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

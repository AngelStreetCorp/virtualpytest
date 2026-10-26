# BUG-0805 — The 24 h Heatmap's hour strip stops hours before "now" (one hour on desktop, four on a phone), so the latest hour cannot be reached

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0805                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-09, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /monitoring/heatmap
- **Viewport / theme:** 1440 px and 390 px

Steps to reproduce:

1. Open `/monitoring/heatmap`; the header reads "showing Today 12:33".
2. Read the hour ticks under the bar, at 1440 px and at 390 px.

**Expected:** The strip covers the 24 hours and marks the current hour.

**Actual:** Desktop ticks end at 11 with 11 marked current (one hour stale). Phone ticks are 12, 16, 20, 00, 04, 08 and 08 is marked current while the header says 12:34; hours 09 to 12 have no tick and the red incident band sits on 08.

Evidence:

- [phone-heatmap-strip.png](../tasks/qa-evidence/analyst/phone-heatmap-strip.png)
- [heat-heatmap-hours-desktop.png](../tasks/qa-evidence/analyst/heat-heatmap-hours-desktop.png)

## Root cause

`frontend/src/components/MosaicPlayer.tsx:318-327`: on a compact layout `hourStep = 4` and `Math.ceil(24 / hourStep)` = 6 marks.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

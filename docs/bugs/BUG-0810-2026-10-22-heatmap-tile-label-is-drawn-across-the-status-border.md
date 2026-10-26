# BUG-0810 — The 24 h heatmap draws each device label across the tile's status border, and a long label is cut off

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0810                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Low                                                       |
| Area      | backend / frontend (mosaic renderer)                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-18, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /monitoring/heatmap
- **Viewport / theme:** 1440 px, dark (also the phone layout)

Steps to reproduce:

1. Open `/monitoring/heatmap`.
2. Look at the device name printed on the bottom edge of a tile with a capture.

**Expected:** The label sits inside the tile, clear of the border, fully readable.

**Actual:** The 3 to 4 px green border runs through the characters and "labox-mobile" is cut to "labox-mobil". The text is baked into the server-rendered mosaic image (`MosaicPlayer`, `Heatmap.tsx:216`, `useHeatmap.ts:536`), so the fix belongs in the mosaic renderer.

Evidence:

- [ops-18-heatmap-label-overlap.png](../tasks/qa-evidence/ops/ops-18-heatmap-label-overlap.png)

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

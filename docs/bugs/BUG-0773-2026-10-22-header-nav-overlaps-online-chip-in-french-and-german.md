# BUG-0773 — In French and German the header's "N online" chip is printed on top of the Settings label on every page

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0773                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-09, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** every page (app header)
- **Viewport / theme:** 1440 px, dark, French and German

Steps to reproduce:

1. Set the language to French (Settings > Appearance) or German.
2. Open any page.
3. Look at the top right of the header, left of the bell.

**Expected:** "Paramètres" with its chevron and the online chip "1 en ligne" side by side and readable.

**Actual:** They are printed over each other: French reads "Paramèt<chip>es", German "Einstell<chip>ungen" with the chevron overwritten. English is fine because its labels are narrower.

Evidence:

- [ops-09-header-overlap-fr.png](../tasks/qa-evidence/ops/ops-09-header-overlap-fr.png)
- [ops-09-header-overlap-de.png](../tasks/qa-evidence/ops/ops-09-header-overlap-de.png)
- Fix evidence: [before FR](../tasks/qa-evidence/fix/bug-0773-before-fr.png) · [after FR](../tasks/qa-evidence/fix/bug-0773-after-fr.png) · [before DE](../tasks/qa-evidence/fix/bug-0773-before-de.png) · [after DE](../tasks/qa-evidence/fix/bug-0773-after-de.png) · [after EN](../tasks/qa-evidence/fix/bug-0773-after-en.png)

## Root cause

The nav row is `flexWrap: 'nowrap'` with no overflow clipping (`frontend/src/components/common/Navigation_Bar.tsx:139-148`) inside a `flex: 1; minWidth: 0` box (`frontend/src/App.tsx:435`); the buttons do not shrink, so the row paints over the right-hand `ModSlot name="app.header"` (`App.tsx:441`).

Measured on the worktree build (1440 px, `getBoundingClientRect()`), the header's three zones are:

| zone | width |
|---|---|
| logo + "VirtualPyTest" + scope picker (`flexShrink: 0`) | 347 px |
| nav row (`flex: 1; minWidth: 0`) | 910 px |
| online chip + bell + PiP + menu (`flexShrink: 0`) | 127 px |

The nav row's **items** carry `flexShrink: 0` and `whiteSpace: 'nowrap'`, so the row's content width
is the sum of the labels plus `12 px` of padding per side on each of the ten items — 240 px of pure
padding. That content is **908 px in French** and **929 px in German** against a 910 px box: the row
had **no slack at all**. English fits because its labels are a little shorter (its `space-between`
gaps absorb the difference — 96 px of free space), which is why only French and German showed it.

The right-hand zone then grew by the chip ("1 en ligne", 76 px). The nav **box** did shrink (910 →
816 px, it is `flex: 1`), but its **content** could not (the items do not shrink), so the row
overflowed its own box by 92 px and painted over the chip and the bell:

| measured | French | German | English |
|---|---|---|---|
| nav content vs box (no chip) | 908 / 910 | 929 / 910 | 814 / 910 |
| overlap on the right zone (with chip) | **+76 px** | **+97 px** | −16 px (none) |

German overlapped by 19 px **even without** the chip.

## Fix

The nav row may never paint over the zone on its right, and the labels must stay readable, so:

- **The items shrink and the label is what gets cut.** `navItemSx` now sets `flexShrink: 1` and
  `minWidth: 0` (`frontend/src/components/common/Navigation_ItemStyle.tsx`), and every label is
  wrapped in a block-level span with `text-overflow: ellipsis` (`NavLabel`, same file). The dropdown
  caret keeps its size (`& .MuiButton-endIcon { flexShrink: 0 }`), so only the word is cut.
- **The row clips** (`overflow: hidden` on the nav row box in `Navigation_Bar.tsx`), so even a
  pathological label can never reach the chip.
- **The padding is halved** — 12 px per side was 240 px of padding for ten items, more than the
  chip needs. It is now 6 px per side, which gives the row back 120 px: French needs 908 − 120 =
  788 px and German 929 − 120 = 809 px, both inside the 816 px the chip leaves. The hover underline
  follows the padding (`left`/`right: 6`), so it still sits exactly under the word.
- **A cut label keeps its full text** in a native tooltip (`NavLabel` watches the span with a
  `ResizeObserver`), so a screen narrower than 1440 px still says what the item is.

`Navigation_ItemStyle.ts` became `Navigation_ItemStyle.tsx` (it now renders a component).

## Tests

`tests/frontend/TopNavRow.test.tsx` — 3 cases:

1. the label styles cut a long label (`ellipsis` + `overflow: hidden` + `nowrap` + `minWidth: 0`);
2. an item may shrink (`flexShrink: 1`, `minWidth: 0`, the caret keeps its size) and the padding is
   the trimmed one;
3. the rendered bar: every nav item carries its label in the ellipsis wrapper and the row itself
   clips.

Verified against the pre-fix sources via `git stash`: **2 failed / 1 passed**; on the fixed sources
**3 passed**.

## Verification

Measured on the worktree build at 1440 px (Vite dev + the live backend), with the chip injected in
the header's right zone (the real chip only renders when the presence socket delivers data, which
the preview's plain-HTTP forwarder cannot do):

| | French | German | English |
|---|---|---|---|
| overlap with the right zone, before the fix | **+76 px** | **+97 px** | −16 px |
| overlap with the right zone, after the fix | **−16 px** (clear) | **−16 px** (clear) | **−16 px** (clear) |
| labels cut after the fix | none | none | none |

Checked in dark and light, at 1440 px, in EN / FR / DE: the chip and the Settings label ("Paramètres"
/ "Einstellungen") stand side by side, both readable, with the caret whole. Screenshots above.

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.

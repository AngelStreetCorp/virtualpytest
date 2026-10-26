---
bug_id: BUG-0572
title: preferences dropdown — minWidth floor, "More"→"Less" label, segment density S/M/L
summary: Three Settings-dropdown polish items the operator flagged from the screenshot: the menu paper width was 240 px while the PreferencesRows footer needs 292 px so the third option in every row clipped, the "More" disclosure label did not flip after expanding, and the segment buttons in the Theme/Colours/Font/Size/Language/Navbar rows were a touch too big with no user knob.
tags: [ui, preferences, dropdown, i18n, density]
keywords: [preferences_rows, navigation_dropdown, segment_button, density, sm_md_lg, more_less, footer_minwidth]
created: 2026-10-16
---

# BUG-0572

## Symptom
Three things on the Settings dropdown that came out of the operator's screenshot (capture: `2026/10/16/14-01-47-770_…png`):

- **Menu paper narrower than the footer.** `Navigation_Dropdown` was fixed at `width: 240` (the widest-locale baseline so switching language never resizes the menu), but `PreferencesRows` opens with `minWidth: 292` (76 px label column + 3 × ~70 px segment + 2 px padding each side). The third option in every row (Theme → "System", Colours → third swatch, Font → third "Aa", Size → "A+", Language → third language, Navbar → third glyph) clipped past the right edge of the paper.
- **"More" stays "More" after expanding.** The disclosure button used the static label `t("More")` with the chevron rotating to mark the open state, so a user opening the Font/Size/Language/Navbar block saw no textual confirmation that the section had expanded — only the icon moved. The aria-label flipped ("Expand" / "Collapse") but the visible label did not.
- **Segment buttons a touch too big, no user choice.** Every segment in the Theme/Colours/Font/Size/Language/Navbar rows was hard-coded to `height: 32` (the old baseline). Combined with the 240 px paper, this amplified the third-option clip. The operator had no S/M/L knob for the segment height — the existing "Size" row only multiplies the typography scale globally, so picking `sm` shrinks the whole UI but does not give them a denser preference list.

## Fix

### `frontend/src/components/common/Navigation_Dropdown.tsx` + `…/types/pages/Navigation_Types.ts`
Added an optional `minWidth` prop (default `240`, the existing widest-locale baseline) to `NavigationDropdownProps`. The Menu's `PaperProps.sx.width` became `minWidth` so the rendered width is `max(minWidth, content width)` — smaller dropdowns keep the 240 baseline, wider footers (PreferencesRows) push the paper to grow. The Settings dropdown now passes `minWidth={296}` (PreferencesRows minWidth 292 + 4 px slack) so the footer never clips, and the comment explains the change from fixed width to minWidth so the next agent does not regress it.

### `frontend/src/components/common/Navigation_Bar.tsx`
The Settings `<NavigationDropdown>` now passes `minWidth={296}` (the other five dropdowns still default to 240). One-line change; the comment cross-references this BUG so a future widening of the footer bumps the floor at the same site.

### `frontend/src/components/common/PreferencesRows.tsx`
Three pieces, one file:

1. **"More" label flips to "Less".** Line 316: `{extrasOpen ? t("Less") : t("More")}`. The aria-label kept its separate "Expand" / "Collapse" text since the two are not the same intent (one describes what the button does, the other names the section being opened). New translation keys `"Less"` in `fr.json` ("Moins") and `de.json` ("Weniger").
2. **Segment density S/M/L.** A new local preference stored in `localStorage` under `virtualpytest:ui:segmentDensity` (parallel to the existing `virtualpytest:theme:size` key — separate, because density is per-user, not per-theme, and should not multiply the typography scale). Three values:
   - `sm` → 20 px button height, `microMeta` icon (10 px) — the tight, dense option.
   - `md` → 22 px button height, `caption` icon (12 px) — the new default. Three notches smaller than the original 32 px so the segments read as chips inside a 244 px menu, not buttons.
   - `lg` → 26 px button height, `body` icon (13 px) — the roomy option for users who want a bigger tap target.
   
   Loaded via `loadSegmentDensity()` in `constants/themeStore.ts`, persisted via `saveSegmentDensity()`, default `md` if the key is absent. The new row sits between **Colours** and **More** so the operator can see and change it without expanding — same UX as the existing top two rows.

**Revised cut (post-deploy feedback, 2026-10-16 14:22):** the first deploy floored the menu to 296 px with a 28 px default button — bigger than the user wanted, not smaller. The revised defaults shrink the menu AND the buttons together: `minWidth: 292 → 244` (the label column 76 → 56 px, the inner gap 0.75 → 0.5, the padding 16 → 12 px), so the three segments now sit at ~50 px each, and the density defaults are 20 / 22 / 26 (was 26 / 28 / 32). The Settings `<NavigationDropdown>` floor drops to 248 px to match. The Colours swatch drops from 14 → 10 px, the inline edit badge from 16 → 12 px, and the `NavHoverMark` SVG from 18 → 14 px to keep the icons proportional to the smaller button.

**Third cut (post-deploy feedback, 2026-10-16 14:40):** the second cut still felt too big — the user did not want a density S/M/L control, they wanted the existing buttons themselves to be smaller so the menu could shrink. The Density row and the per-user `virtualpytest:ui:segmentDensity` preference are gone; `segmentSx` / `sizeSegmentSx` no longer take a density param; `DENSITY_IDS` / `DENSITY_VALUES` / `DENSITY_NAMES` / `handleDensityChange` / `loadSegmentDensity` / `saveSegmentDensity` / `DENSITY_KEY` / `SegmentDensity` are removed from `themeStore.ts` and `fr.json` / `de.json` (the "Density" key is gone — the `Less` key stays because the More→Less toggle still uses it). The new defaults:

- segment height: 20 px (down from 22 / 28 / 32 — the smallest we can ship without the button looking like a divider)
- segment icon font: 10 px (`microMeta`, down from 12 / 13 / 14)
- Size row icon font: 12 px (`caption`, down from 12 / 13)
- `PreferencesRows` `minWidth: 244 → 216`, `px: 1.5 → 1.25` (10 px each side, was 12), `pb: 1 → 0.75`
- Settings `<NavigationDropdown>` `minWidth` override removed — the 240 px widest-locale baseline now wraps the 216 px footer, so all six dropdowns share the same floor again (language switching still does not resize them)
- three segments fit at ~41 px each inside a 216 px paper, which is the tightest that still reads "A-A+" at the 12 px caption font

The More → Less toggle and the inner gap / label width reductions from the second cut stay. Net change from the original (32 px button, 296 px menu) to the third cut (20 px button, 216 px menu inside a 240 px menu): **−80 px menu width, −12 px button height**.
3. **`segmentSx` + `sizeSegmentSx` take a density.** All six call sites (Theme, Colours, Colours custom-edit, Colours "+", Font, Size, Language, Navbar, plus the new Density row) now pass `density` through. The Size row's icon scale stays slightly larger than the generic icon scale so the `sm` density still keeps the shrink/both/grow glyph legible.

### `frontend/src/constants/themeStore.ts`
Added `DENSITY_KEY`, `SegmentDensity`, `loadSegmentDensity()`, `saveSegmentDensity()`. Mirrors the `userSize` pattern (storage + types), but with a hard `md` default since density is purely a UI knob, not a theme property.

### `frontend/src/i18n/locales/fr.json` + `de.json`
- `"Less": "Moins"` (fr) / `"Weniger"` (de)
- `"Density": "Densité"` (fr) / `"Dichte"` (de)

English is the implicit source key in this i18n (see `i18n/index.ts` TASK-53), so no `en.json` change is needed.

## How to verify
1. Open the Settings dropdown in the navbar. The menu paper is at least 296 px wide; every row (Theme, Colours, Density, More→Font/Size/Language/Navbar) shows all three options without clipping. Switching the language to DE or FR does not resize the menu.
2. Click the **More** disclosure. The visible label flips from "More" to "Less", the chevron rotates, and the four extra rows reveal. Click again: label flips back to "More" and the rows collapse.
3. Click **S** in the new Density row. Every segment button across the menu shrinks to 26 px; the footer still fits. **L** restores the original 32 px baseline. The choice survives a reload (read from `localStorage` on mount). Pick `md` to land on the new default.
4. Resize the viewport to a phone width and open the More tab — the phone More menu's PreferencesRows footer grows the menu paper the same way (same component, same `minWidth` semantics).

## How not to regress
- Do not put `width: 240` back in `Navigation_Dropdown` PaperProps. The dropdown is now `minWidth` so the footer can push the paper wider; reverting to fixed width will clip PreferencesRows again. If a future footer needs more than 296 px, bump the `minWidth` on the call site, not the default.
- The "More" → "Less" label and the `aria-label` "Expand" / "Collapse" are intentionally different. The label names the section, the aria-label names the action — keep them apart.
- Density is a per-user preference stored in `virtualpytest:ui:segmentDensity`. Do not fold it into the existing `Size` row — they answer different questions (Size = "how big is the UI", Density = "how dense is this preference list"). The two already coexist (Size is in the More block, Density is at the top) and that is the right place for each.

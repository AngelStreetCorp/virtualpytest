# BUG-0553 — REC preview card header carries too much chrome; status / lock / AVQ / Localize / tags clog it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                   |
|-----------|-----------------------------------------|
| ID        | BUG-0553                                |
| Reported  | 2026-10-15                              |
| Status    | Fixed (pending deploy)                  |
| Severity  | Low (cosmetic / information density)    |
| Area      | frontend / `rec/` / preview card header |
| Fixed in  | build 90145 |

---

## Symptom

On a 16-tile Rec page the preview header read, left to right:
`stb4 - vpt-pi1   [🏷️2]   [⊕]   [〰️]   [🟢]   [⭐]`
— five icons between the device name and the favorite star. On the wider cards that fit
the full `displayName`, the icons only take ~110 px and feel busy; on the narrower phone
tiles they squeeze the name and force it to ellipsize.

The five items were, in order:

1. **tags** — collapsed "2" chip from `deviceFlags`
2. **localize** — `LocalizeButton` (target icon)
3. **avq** — the `featureDeviceLinks()` AVQ entry (audio/activity PNG icon)
4. **status** — `DeviceStatusChip` (green / yellow / red dot)
5. *(favorite star, kept)*

The lock indicator is part of the same header block too — it only renders when a script
is driving the device, but it is a sixth icon the header has to make room for.

## Root cause

The header is the natural "everything I might want to know about a device" slot and
accumulated one icon per feature over time, without anybody pruning. The status dot and
the lock indicator duplicate state that the `RunningScriptNameBadge` in the card body
already carries (when something is running) — the header version is the redundant one
when both render.

The Localize button opens the same Localize popover every preview in the page already
shows a verdict for (the `LocalizeVideoBadge` on the video), so the button is a second
entry to the same answer. The tag chip is a "what is this" signal that the user can
already read off the active filter pills on the same page.

The AVQ link points at a full per-device page; the preview's header is the wrong place
for a deep-link, and the icon is a custom PNG that the rest of the chrome does not use.

## Fix

Slimmed the header down to its two essential slots: the `displayName` (with the
maintenance badge and the device-info tooltip) on the left, the favorite star on the
right, and the edit-mode checkbox between them when relevant. The removed blocks
(`deviceFlags` chip, `LockIcon` tooltip, `LocalizeButton`, `featureDeviceLinks()`
IconButtons, `DeviceStatusChip`) are gone from the JSX, the imports they brought
(`TagIcon`, `Lock as LockIcon`, `useNavigate`, `featureDeviceLinks`, `LocalizeButton`
+ `LOCALIZE_OFF_TITLE` + `localizeOff`, `DeviceStatusChip`, `useHostControl`,
`getLockTimingLines`, `Tooltip`) are gone too, and the dead state (`hasManualControl`,
`lockInfo`, `lockTiming`) is gone with them. `deviceFlags`, `activeFlagFilters` and
`onFlagClick` stay on the prop interface as `_`-prefixed destructured args so
`Rec.tsx`'s memo comparator keeps working without a caller change.

The full lock / script state still appears in the `RunningScriptNameBadge` in the card
body (the existing per-run badge that already shows `Run by: … · Script: …`), so no
information is lost — only the redundant header chrome is.

## Verification

- `tsc --noEmit` clean.
- `eslint src/components/rec/RecHostPreview.tsx --max-warnings 0` clean.
- Visual: any device tile on the Rec page now shows `stb4 - vpt-pi1` (or whichever
  displayName) + the maintenance badge + ⭐. In edit mode a checkbox sits between the
  name and the star. Lock / status / tags / Localize / AVQ no longer render in the
  header.

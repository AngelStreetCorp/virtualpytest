# BUG-0861 — The red "Monitoring problem" badge wore the amber warning triangle

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0861                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On the dashboard, the red **"Monitoring problem"** badge sat next to the amber
**"N in warning"** badge, and both wore the **same icon**: the warning triangle. The red badge
means a monitoring problem is open — an error — yet its icon said "warning", exactly like the
amber badge next to it. The icon is the faster read, so the badge announced the wrong severity.

The same happened on the dashboard's own **"N in error"** chip, which used MUI's `Warning`
(a red triangle) instead of the error glyph the rest of the platform uses.

The badges do not need a glyph at all (owner): the row is now text only.

## Root cause

- `frontend/src/components/notifications/MonitoringProblemChip.tsx` rendered
  `icon={<AppIcon name="warning" />}` on a chip with `color="error"` — the amber warning triangle
  (`WarningAmberOutlined`) on a red chip.
- `frontend/src/components/dashboard/HostsDevicesView.tsx` imported MUI's `Warning` as
  `ErrorBadgeIcon` (a triangle) next to `WarningAmber` as `WarningBadgeIcon`, so the error chip
  and the warning chip shared a glyph and differed only by colour.

The icon palette already carries the right glyph: `AppIcon name="error"` is `ErrorOutline` (a
circle with "!"), the platform's error mark.

## Fix

The badge row is now **text only**. The owner asked for it to be simple: no icon, no glyph on any
of the health badges.

- The "Monitoring problem" chip, the "N in error" chip and the "N in warning" chip (desktop and
  mobile header) all render their label alone — the `icon` prop is gone, and the icon imports with
  it.
- The colour and the words carry the meaning: red "Monitoring problem" / "N in error", amber
  "N in warning". The glyphs were never reliable anyway — the red chip wore the amber triangle.

## Verification

- `tests/frontend/MonitoringProblemChip.test.tsx` renders the chip with one open problem and
  asserts it carries **no** icon at all (no `svg` inside the chip, neither `ErrorOutlineIcon` nor
  `WarningAmberOutlinedIcon`), that it still says "Monitoring problem", and that it renders nothing
  when no problem is open.
- On the dashboard the three badges are plain words in their colours.

# BUG-0845 — Back / Home / Menu on the phone remote render as narrow slivers, not square

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0845                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Take Control on an Android phone (Take Control → Device Controls). The **Back**, **Home** and
**Menu** icon buttons next to the OK / arrow D-pad render as tall, narrow slivers instead of
squares — roughly 22 px wide against 32 px tall — and the row keeps a visibly empty strip on
its right-hand side. The D-pad buttons right beside them are proper 36 × 36 squares, so the two
groups look like they belong to different controls.

## Root cause

`flex: 1` was on the `IconButton`, but the `IconButton` is not a flex item. `Tooltip` requires a
single child that can hold a ref, so each button is wrapped:

```tsx
<Tooltip title="Back (KEYCODE_BACK)">
  <span>                      {/* <- this is the row's flex item */}
    <IconButton sx={{ flex: 1, height: 32, p: 0 }}>   {/* flex has no effect here */}
```

`flex` only applies to a flex item, and the wrapper `<span>` was a plain block box (blockified
because it is a flex item) with `flex: 0 1 auto`, so it shrank to its max-content width. The
`IconButton` inside it then sized to that content. MUI's `IconButton` base style sets `padding`
and `fontSize` but **no `width`** (`node_modules/@mui/material/IconButton/IconButton.js`), so with
`p: 0` the button collapsed to the bare icon: 20 px (`fontSize="small"` = 1.25 rem) plus the 2 px
border = **22 px**, against the pinned `height: 32`.

The row itself was fine — it is `flex: 1` and did receive all the leftover width. Nothing ever
claimed it, which is exactly the empty strip on the right.

The sizing was introduced in `44db785848` ("Back / Home / Menu as icon buttons"), whose message
describes "each icon flex:1". The intent was right; the property landed one element too deep, so
it had never worked and the buttons were never the ~1/3-width the commit intended.

## Fix

The grow moves onto the element that is actually the flex item, and the square comes from
`aspectRatio` instead of a hard-coded height:

- `tooltipWrapperSx` (`flex: 1`, `minWidth: 28`, `display: 'flex'`) on the wrapper, turning it into
  a flex container so the `flex: 1` on the `IconButton` actually applies. The wrapper is
  `Box component="span"`, not a bare `<span>`: `sx` is an MUI prop and a plain DOM `<span>` does
  not have it (`tsc` rejects `<span sx={…}>`).
- `aspectRatio: '1 / 1'` in `iconBtnSx`, replacing `height: 32`. Each button is now square at
  whatever width the row hands it, so the shape holds on a narrow panel instead of being correct
  at exactly one width. `minWidth: 28` keeps the tap target usable when the panel is squeezed.
- Panel content cap `230px` → `238px`: 118 px D-pad + 8 px row gap + 3 × 36 px buttons + 2 × 2 px
  icon gaps = 238. That puts each button at exactly **36 × 36**, matching the D-pad cells. The
  container is `300px` wide, so the 8 px costs nothing and every other row in the panel already
  stretches (`flex: 1` / `minWidth: 0` / `fullWidth`), so nothing else moves.

## Verification

Take Control on an Android phone → Device Controls: **Back**, **Home** and **Menu** render as
36 × 36 squares, the same size and baseline as the OK button, and the row ends flush with the
right edge of the panel — no empty strip. Narrow the panel and the three buttons stay square
rather than turning back into slivers. Each tooltip ("Back (KEYCODE_BACK)", "Home
(KEYCODE_HOME)", "Menu / recents (KEYCODE_APP_SWITCH)") still appears on hover, including while
disconnected.

`tsc --noEmit` clean, `ui-check.mjs` clean, `vite build` clean.
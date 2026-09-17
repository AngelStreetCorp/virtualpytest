# BUG-0124 — Every long mobile page clips its last ~56px under the bottom nav

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                            |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0124                                                         |
| Reported  | 2026-09-16 ("the section is cut by the navbar at the bottom")     |
| Status    | Fixed — measured on the reporting device (Galaxy S21 Ultra)       |
| Severity  | Medium (every mobile page taller than the viewport)               |
| Area      | `frontend/src/App.tsx` (mobile layout container)                  |
| Fixed in  | build 9151                                                        |
| Commit    | TBD                                                              |

---

## Symptom

On the phone, the "Last runs" card on Run Tests showed 4 of its 5 rows and the 4th was
sliced in half by the bottom navigation. Scrolling did not help — the page had almost
nothing left to scroll.

Measured in the app's WebView over CDP, before the fix:

| | value |
|---|---|
| scroll container | `clientHeight` 779, `scrollHeight` 827 → **48px of scroll** |
| "Last runs" card | top 631, **bottom 811** |
| bottom nav | top **723**, height 56 |
| viewport | 778 |

Scrolling all 48px still left the card's bottom at 763 — 40px underneath a nav that
starts at 723. Not specific to Run Tests: the Dashboard's last host card was clipped the
same way.

## Root cause

`ConditionalContainer`'s mobile branch already reserved the nav's footprint:

```js
pb: 'calc(64px + env(safe-area-inset-bottom, 0px))',
flex: 1,
minHeight: 0,
```

but `flex: 1` (i.e. `flex: 1 1 0%`) with `minHeight: 0` **caps that box at the flex
line's height** — the viewport. A page taller than the viewport therefore overflows its
own container (`overflow` is `visible`, so it still paints and still extends the
scroller's `scrollHeight`, which is why there was *some* scroll).

And because the padding belongs to the capped box, it sits *inside* it — above the
escaping content rather than below it. Measured: container 763px tall holding 819px of
content, so the reservation was 56px of dead space in the middle of the page and zero at
the end. The reservation was defeated in exactly the case it existed for.

`minHeight: 0` is what allowed the shrink; a flex item's default `min-height: auto`
would have refused to go below its content.

## Fix

`flex: '1 0 auto'` and drop `minHeight: 0` (`frontend/src/App.tsx`):

- short page — `flex-grow: 1` still fills the screen, unchanged;
- long page — `flex-basis: auto` makes the box as tall as its content and
  `flex-shrink: 0` keeps it there, so the scroll container scrolls through the content
  *and* its 64px of bottom padding.

## Verification

Same measurement on the same phone, APK 1.0.26, scrolled to the very bottom:

| | before | after |
|---|---|---|
| container height | 763 (content 819) | **933** (content 933) |
| scrollable | 48px | **170px** |
| "Last runs" bottom at full scroll | 763 | **690** |
| nav top | 723 | 723 |
| rows visible | 4, last one sliced | **all 5**, 33px clear of the nav |

# BUG-0525 — Floating Ask AI button overlays the footer copyright line

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0525                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `b70b833d7`                                                  |

---

## Symptom

The purple floating **Ask AI** button (bottom-left, `Cmd+K`) sits on top of the
"© 202…" footer text whenever the page is scrolled to the very bottom. The button
is opaque and round, so it covers part of the copyright line on every page with a
long enough body — Settings, Monitoring, the docs pages, etc.

Reproduces on desktop at any window width where the Fab is shown
(`useResponsiveMode().isDesktop`). Mobile and tablet already hide the floating
button (`AIOmniOverlay.tsx` — `hideFloatingAiButton` covers `isMobile` and
`isTablet`), so only desktop is affected.

## Root cause

`frontend/src/components/ai/AIOmniOverlay.tsx` placed the floating button at
`bottom: 24, left: 24`. The `Footer` is an in-flow `<Paper>` at the bottom of
`<App>` (`minHeight: 16` inner row + Paper chrome ≈ 40 px) — it is **not**
`position: fixed`. When the page is scrolled all the way down, the footer sits
right where the Fab is anchored: the 24 px gap from the viewport edge is
smaller than the footer's own height, so the Fab lands on top of the copyright
text.

## Fix

`frontend/src/components/ai/AIOmniOverlay.tsx` — bumped the Fab's `bottom` from
`24` to `80`. The Fab is `size="medium"` (≈ 56 px tall), so 80 px leaves a
≈ 24 px visual gap above the footer — same offset it had from the viewport
edge before, now measuring from the footer's top edge.

## Verification

Open `https://virtualpytest.angelstreet.io/<any long page>` on desktop, scroll
to the bottom: the **Ask AI** button sits above the "© 202…" line, no overlap.
The footer text is fully readable and the button is not clipped at any desktop
viewport. Mobile/tablet keep hiding the Fab as before.
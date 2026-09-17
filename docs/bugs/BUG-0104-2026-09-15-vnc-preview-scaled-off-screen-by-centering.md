# BUG-0104 — VNC preview cards render black: centering pushes the scaled iframe out of view

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0104                                                                    |
| Reported  | 2026-09-15 (`host-clone-1`, `labox-web` on Awesomation — "not showing anything anymore") |
| Description | Regression introduced by `447dabe3cb`, surfaced by the 2026-09-15 frontend deploy |
| Status    | Closed — fix reverted 2026-09-15, addressed on the QualiAI side              |
| Severity  | Medium (every VNC device preview is a black card on every server)           |
| Area      | `frontend/src/components/rec/RecHostPreview.tsx`                            |
| Fixed in  | — (internal: reverted, nothing shipped)                                      |
| Commit    | this commit                                                                 |

---

## Symptom

Device cards for `host_vnc` devices show a black rectangle. The host is `online`, the page and
the noVNC assets load, and the WebSocket upgrade succeeds:

```
/host/host-clone-1/vnc_lite.html   200  6335 bytes  text/html
/host/host-clone-1/core/rfb.js     200  105544 bytes
/host/host-clone-1/websockify      101 Switching Protocols   (--http1.1)
```

So nothing is wrong below the browser. The iframe is simply not where the card is.

## Cause

`calculateVncScaling({width: 300, height: 150})` keeps the iframe's **layout box at the full
remote desktop size** and shrinks the render with a transform:

```
width: 1440px, height: 847px, transform: scale(0.177), transformOrigin: 'top left'
```

`447dabe3cb` then centred that box in the card (`display:flex; align-items:center;
justify-content:center`). Centring a 1440×847 box inside a ~300×150 card offsets it about
570 px left and 350 px up — and because the transform scales about the box's **top-left**, the
painted 255×150 area travels with that corner, landing entirely outside the card. The card is
black not because nothing rendered, but because what rendered is off-screen.

## Fix

Scale about the centre (`transformOrigin: 'center center'`) in the preview, which is where the
flex centring puts the box — so the painted area lands on the card's centre, which is what
`447dabe3cb` was reaching for. The override is local to `RecHostPreview`; `calculateVncScaling`
keeps its top-left origin for `VNCStream`, which positions the iframe itself.

---

## Reverted 2026-09-15

`transformOrigin: 'center center'` was reverted at the user's request: it caused a regression on
VirtualPyTest, where the VNC previews had not been the reported problem in the first place (the
zoomed rendering was on QualiAI, and that is fixed on the QualiAI side with noVNC's own `scale`
param). `RecHostPreview.tsx` is byte-identical to its state before the change.

The analysis above is left for whoever picks this up, with one correction to it: the iframe is a
**flex item**, so `flex-shrink: 1` (the default) shrinks its 1440 px base width to the card
before the transform applies — the render is not pushed off-card as claimed, it is shrunk twice
and ends up tiny in the corner. Any real fix therefore has to deal with `flexShrink` as well as
the transform origin, and should be verified in a browser against a live VNC host rather than
reasoned about from the CSS.


---

## Resolved 2026-09-15 — measured, not reasoned

Measured on the live page with CDP (`getBoundingClientRect` on the iframe and its card), which
is what both analyses above were missing:

| | painted iframe | card |
|---|---|---|
| x | 208 | 221 |
| **y** | **-188** | **163** |
| w x h | 53 x 150 | 274 x 146 |

`transformOrigin: 0px 0px`, computed layout box `300px x 847px`.

**Both earlier analyses were half right, and both drew the wrong conclusion.**

- The original claim "pushed off-card" is true **vertically** — the painted top edge is 351 px
  above the card — but not horizontally (x 208 vs 221, only 13 px off). The "~570 px left" figure
  was wrong.
- The revert note's correction is true about `flex-shrink` — the box really is shrunk 1440 -> 300
  and then scaled again, giving a 53 px sliver instead of the intended 255 px — but wrong that the
  render "is not pushed off-card". It is, by 351 px.

Both effects have the same single cause: **the container was made a flex container.** The
transform scheme in `calculateVncScaling` only works for a **block** child of a
`position:relative; overflow:hidden` box — then the 1440x847 layout box starts at the card's
top-left, nothing shrinks it, and `scale(0.177)` about `top left` paints ~255x150 exactly over a
~274x146 card.

**Fix:** remove `display:flex; align-items:center; justify-content:center` from the container.
`RecHostPreview.tsx` is now functionally identical to its state before `447dabe3cb`, with a
comment recording why the container must not become a flex container.

The premise of `447dabe3cb` ("it sat flush left with the rest of the card black") was itself
mistaken: 255 px of painted content in a 274 px card is very nearly the full width, not a sliver
needing centering.

**Sturdier follow-up (not done here):** drop the CSS transform altogether and let noVNC scale
itself — `vnc_lite.html` reads `?scale=true` into `rfb.scaleViewport` (line 181), which is how
QualiAI handles it. That removes the 1440x847-box-plus-transform coupling that has now produced
three wrong analyses.

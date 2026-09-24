# `public/vendor` — third-party logos

Every third-party mark the UI shows lives here, and **only** here.

## Why this is not in `public/brand`

`public/brand` is customer-owned. `update_core.sh` carries
`--exclude='frontend/public/brand'` so that a platform redeploy can never wipe an
overlay's logo — which also means **nothing new put there ever reaches a deployed VM**.
A mark placed in `public/brand` serves `index.html` through the SPA fallback and renders
as a broken image, with a `200` that hides it from a naive check.

`public/vendor` is platform-owned and rsyncs like any other source path. Put third-party
marks here. Put a customer's own branding in `public/brand`.

## Layout

| Folder | Holds | Read by |
|---|---|---|
| `farm/` | the cloud device farms — `<slug>-mark.svg` (square mark) and `<slug>.svg` (wordmark) | `components/rec/DeviceFarmBadge.tsx` (mark, on every farm device preview), `docs/features/README.md` (wordmark), and the docs integrations grid |
| `integrations/` | everything else on the integrations grid — `<slug>-mark.svg` only | `components/docs/integrationsData.ts` |

## Adding a mark

1. Drop `<slug>-mark.svg` into `integrations/` (or `farm/` if it is a device farm, which
   also wants a wordmark).
2. Give the file a header comment naming the source and the trademark owner, the way the
   existing files do.
3. Bake the fill into the `<svg>` element. **Check it on the dark theme**: several official
   hexes are near-black and vanish there — Slack's `#4A154B` is why `slack-mark.svg` is drawn
   in the palette blue `#36C5F0`, and LambdaTest's `#121212` was why its mark took the accent
   from their own site. Both say so in their header comment.
4. Point `logo` at it in `components/docs/integrationsData.ts`. Until you do, that card
   renders a monogram tile, which is the signal that a mark is missing.

A mark a farm *and* the grid both show is stored once, under `farm/`, and referenced twice.
Do not copy it.

## Trademarks

These are the trademarks of their respective owners. They are shown to indicate
compatibility only — VirtualPyTest is not affiliated with or endorsed by any of them.

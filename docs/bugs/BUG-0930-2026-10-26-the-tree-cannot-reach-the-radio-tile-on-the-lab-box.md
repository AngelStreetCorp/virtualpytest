# BUG-0930 — The tree cannot reach the radio tile on the lab box: the reference picture was captured with another app-store layout

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0930                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | userinterface (navigation tree, app-store nodes)             |
| Fixed in  | Unreleased                                                   |
| Commit    | —                                                            |

---

## Symptom

The content suite's radio case cannot open the radio surface on the lab
set-top box. The tree's own route (`apps_dazn` → `apps_radio`) runs and lands
on a **different tile**: the reference picture of the radio tile does not match
the screen any more (*"reference: apps_radio.jpg not detected in source …
Match score: 0.236 (required: 0.800)"*), and the focus ends up one tile to the
left of the radio one.

The radio app itself is on that box: the screen shows the tile with the word
*Radio* under it, in the second row of the app store.

## Root cause

The tree's reference picture for `apps_radio` was captured with a different
layout of the app store than the one the box shows now:

- at capture time the radio tile sat in the **first visible position** of the
  grid, so the picture is a crop of that position;
- the box now shows the radio tile in the **second row** (the media row), and
  the grid is scrolled, so the crop of the reference picture covers the tile of
  the row above.

Two consequences follow, and both are visible in the run:

1. The reference picture cannot match any screen, so the node's own
   verification fails on every box with the current layout.
2. The route that leads to the tile moves horizontally inside the top row and
   lands on another tile of that row, because the tile the tree knows is no
   longer where the tree believes it is.

## Fix

**Not fixed here — this is a tree gap, and the tree is a shared artefact.**

The repair belongs to the tree-repair flow, which recaptures the node's
reference on the box and writes the result as a **new variant** (the base tree
stays untouched):

1. recapture the reference picture of the radio tile on the box, with the tile
   where the box shows it;
2. correct the route into the tile so that the focus lands on the radio tile
   and not on a neighbour;
3. check the same for the other app-store tiles of that box, since the whole
   row is affected by the same scroll.

What the **suite** does meanwhile is to say the truth: the radio case reads the
screen's own text before it gives up, and a radio tile that is on the screen
makes the row a *tree gap* (infra) with the reason *"the Radio app IS on this
box's app store, but the tree's route for `apps_radio` does not reach it: the
tree's reference picture is stale for this layout"* — never a defect of the
product. See [BUG-0929](BUG-0929-2026-10-26-the-suite-called-our-own-problems-defects-of-the-app.md).

## Verification

The suite's radio case on the lab set-top box reports the tree gap with the
tile's own text as evidence, and the run of 2026-10-26 01:37 shows the failed
comparison with the score the tree measured. The run that reads the screen —
the one that asks the box what it is actually showing — is the run of
2026-10-26 02:20 on the same box, and it is the one that reports the tree gap
by name.

After the tree repair: the radio case reaches the radio app's own screen and
the run reports what the app plays there (the audio probe decides, because a
radio station is a still picture with sound).

## Evidence

- The run of 2026-10-26 01:37 on `vpt-pi1/device4`:
  `~/vpt-deliverables/vod-radio-runs/2026-10-26T01-37-40Z/` — the radio row:
  *"reference: apps_radio.jpg not detected in source … Match score: 0.236
  (required: 0.800)"*.
- The run of 2026-10-26 02:20 on the same box:
  `~/vpt-deliverables/vod-radio-runs/2026-10-26T02-20-26Z-stbradio2/` — the radio
  row reads the screen and reports the tree gap by name, with
  `radio_tile_on_screen: true` in its evidence.

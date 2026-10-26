# BUG-0836 — the monitor overlay did not sit on the eggs, and its counters were unreadable

**Found** 2026-10-22, on the two synthetic devices of `vpt-lenovo1` after BUG-0833/0834 made them
count at all. **Reported by** the owner, looking at the live stream modal: *"the frame rate at which
we refresh the monitor is not sufficient to see it clearly, the displayed overlay should match the
eggs at all time — that is the difficulty"*.

## What was wrong

The overlay is drawn from a frame JSON on top of a **live** video. The two were never related, so the
boxes showed where the eggs were up to a second ago, on a picture that had moved on:

| link in the chain | what it cost |
|---|---|
| the worker takes the **newest** pending frame, so the frame it analyses is up to one `sample_hz` period old | 250 ms at 4 Hz |
| the analysis itself | ~57 ms of detection |
| the browser asked the server for the newest JSON every **500 ms** | 0-500 ms, average 250 ms |
| the LHLS stream under the overlay is later again | ~1 s |

Three quarters of a second between "this is where the egg was" and "this is what you see". On a
factory belt the eggs move a visible fraction of the frame in that time, so the boxes sat *beside*
the eggs, and no amount of watching made that look like a tracking bug. Nothing in the UI said so:
the FPS line reported the capture rates, which were fine.

The same JSON carried no time of its own. `timestamp` was `datetime.now()` at the **end** of the
analysis, so the client could not even measure how far behind it was, let alone correct for it.

Two readability problems hid the real state behind the noise:

- **The counters wrapped.** `gridTemplateColumns: '1fr 1fr'` with three classes put "Good / Bad" on
  one line and "Unverified" on the next, its number pushed to the far edge of the panel, ~200 px from
  its label. On a 25 %-wide panel in a 1280 player that is two lines that read as one.
- **Every egg wore a `3/3` badge.** 90 eggs, 90 identical labels: a wall of text carrying no
  information, hiding the one label that mattered. And the panel named a verdict for "the last
  checked" egg that could not be found in the picture, because every box was its own class colour.

## Fix

**Hold each box on its object.** The tracker already estimates a centre velocity per track for its
own matching; it is now a public accessor (`_Base.velocity`, BUG-0836) and the pipeline writes it on
every observation as `v: [vx, vy]` px/s. The frame JSON also carries `captured_at`, the capture time
of the frame that was actually analysed (not of the analysis), tracked per device in
`SampledWorkerAnalyzer._latest_ts` and carried into the archive chunk. The client advances each box
by `v x age`, fades it out as the estimate ages past `MAX_LEAD_S` (0.8 s) instead of letting it glide
away, and prints the age next to the FPS line as `sync 250 ms` so the operator can see the truth
rather than guess at it.

**Spend the saving on a higher sample rate.** The lag is dominated by the sample period, so the
detector got cheaper: `detect_width` finds the eggs on an 800 px copy and scales the boxes back.
Measured on the real factory clip at 1280x720: **the same 71 boxes per frame, 32 ms instead of
54** (1.7x). `egg_quality` therefore samples at **8 Hz instead of 4 Hz**, which halves the worst-case
period term. `counting_cars` gets `v` and `captured_at` for free, at its existing 2 Hz.

**Poll faster.** 500 ms -> `POLL_MS` = 120 ms. The monitor writes one JSON per sample, so polling at
a fifth of the old rate was pure added staleness.

**One row per class, with the share.** `Counters` replaces the wrapping grid: dot, label, count and
its percentage of the total on one `white-space: nowrap` row, right-aligned on tabular figures, under
a single stacked bar that shows the split before any number is read. In the narrow panel the label is
dropped and the count and share stay.

**One gold egg.** The track in the "Last checked" panel is drawn in gold (`FOCUS_HEX`) with a 1.8x
stroke, whatever its class colour, and it is the only box that keeps a vote badge once the scene has
more than `BADGE_ALL_UPTO` (12) objects. The panel says "● gold in the picture" so the two agree.

## Measured

| | before | after |
|---|---|---|
| egg detector, 1280x720 real clip | 54 ms, 71.2 boxes/frame | 32 ms, 71.3 boxes/frame (`detect_width: 800`) |
| egg sample rate | 4 Hz | 8 Hz |
| browser poll | 500 ms | 120 ms |
| worst-case period term | 250 ms | 125 ms |
| votes badges on the egg belt | 90 | 1 |
| counters | 3 classes over 2 lines | 3 rows, count + share, no wrap |

Tests: 23 in `tests/frontend/ProfileOverlay.test.tsx` (velocity advance, no-advance without
`captured_at`, fade with age, badges only on the focused item past the threshold, gold on the focus,
the sync line), 99 passed / 2 skipped across `test_egg_quality`, `test_counting_cars` and
`test_monitor_profiles`.

## Measured on the host afterwards, and one thing this changed

Polling `/var/www/html/stream/capture3/hot/metadata/` every 120 ms (as the browser now does) for 25 s
and reading the age of each newly-written frame JSON, on `vpt-lenovo1` device 3:

```
123 distinct newest frames in 25 s = 4.9 Hz
overlay age (now - captured_at):  median 311 ms   p90 537 ms   max 747 ms
  capture -> analysis done:       median 201 ms
  json written -> the poll saw it: median 110 ms
```

Down from a worst case of ~750 ms before, at a median of ~310 ms. **But 4.9 Hz, not 8**: `sample_hz`
is a *ceiling*, and this device's ffmpeg writes captures at 5 fps (`[cap]fps=5`), so the analyzer can
never see more than 5 frames a second. Raising 4 -> 8 Hz buys nothing here; what actually bought the
drop is `detect_width` (the analysis is cheaper, so it keeps up inside the 5 fps it is given) and the
500 -> 120 ms poll. The 8 Hz is kept because it costs nothing and a profile on a 10 fps source does
get the benefit.

That leaves the two real limits on this device, neither of which this fix can remove:

- **the capture rate itself** (5 fps = one frame every 200 ms is the floor on how fresh the boxes can
  ever be), and
- **the monitor noticing the file**: of the 201 ms from capture to analysis done, only ~125 ms is the
  sample period, the rest is the directory watch plus the analysis itself.

`captured_at` is written as **UTC with an offset**, not the naive local time `timestamp` carries: the
client subtracts it from its own clock, and a naive ISO string parses as the *browser's* local time,
so a browser in another timezone would read the age off by hours and shift every box by that much.
That is a silent total failure of the correction, so there is a test pinning the offset.

## Prediction is not enough: the fix that actually works

Measuring the lag and correcting for it was necessary, and **it is not sufficient**. The owner's screenshot
after the first deploy showed `sync 485 ms` and the boxes visibly beside their eggs, and a harness over
two real consecutive captures (boxes from `capture_000463849.jpg`, drawn over `capture_000463851.jpg`,
400 ms later) shows why: a constant-velocity prediction is only right while the motion is constant. Eggs
are picked up, piles shift, the belt speed changes, and every one of those makes the estimate wrong for
exactly as long as the picture is behind. Asking "how stale is it" and then guessing where things went
is the wrong shape of solution, and the `sync` line only ever told you the guess was stale.

**The correct answer is to stop having a lag.** The monitor already knows the frame its boxes came from,
and that capture is on disk: `capture_NNNNNN.jpg` next to `capture_NNNNNN.json`. So when a profile
overlay is drawing, the picture shown *is that capture*, and the boxes sit on it by construction — no
prediction, nothing to drift, no assumption about the scene:

- `AnalysedFrameLayer` renders the analysed capture above the video and below the boxes (zIndex 12,
  between the player and the overlay's 15), and a small switch in the corner offers the smooth live
  stream back for watching the device itself. **Frame-locked is the default.**
- `ProfileOverlay` takes `frameLocked` and then **does not carry the boxes forward** — with no lag left
  there is nothing to correct, and applying the lead anyway would move them off their objects. The FPS
  line says `locked to the analysed frame` instead of a number.
- The hook is called unconditionally; `useOverlayAge` runs either way and only its result is discarded.
  A conditional hook would crash the moment the switch is used (there is a test).

Both modes stay because they answer different questions: frame-locked for checking that the count is
right, live for watching the device. The honest cost of frame-locked is that the picture advances at
the **capture** rate (5 fps on this device) rather than the stream's 10 fps — which is also the ceiling
on how fresh the boxes can ever be, as the measurement above shows.

`v` and `captured_at` are still there and still earn their place: they are what the live mode needs, and
`sync` is what tells an operator the live mode is currently guessing.

> **Follow-up (BUG-0859):** the paragraph above assumed the JSON next to a capture is the JSON of THAT
> capture. It is not: the worker attaches one analysis to every frame's JSON until the next one, so the
> JSON of capture N usually carried the boxes of an older frame while naming capture N. The frame-lock
> therefore drew a newer picture than the boxes, and on a belt every circle landed on bare belt next to
> its egg. The JSON now names the frame the boxes were measured on, exactly like `captured_at` already
> did, and the two agree.

## What this does not do

Frame-locked mode shows one frame at a time at the capture rate, so the picture is not smooth the way a
live stream is; it is meant for reading the overlay, not for judging motion. Prediction, where it is
used at all, is only as good as a constant velocity. An egg that stops, reverses or is picked up is
wrong for as long as the prediction lasts, and after `MAX_LEAD_S` the box fades out rather than
lying. A box that leaves the picture is not drawn again until the next frame JSON. The sync line is
the honest measure of how far the picture is behind; if it reads over ~800 ms, the numbers are still
right (they are counted on the host) but the picture should not be trusted for counting by eye.
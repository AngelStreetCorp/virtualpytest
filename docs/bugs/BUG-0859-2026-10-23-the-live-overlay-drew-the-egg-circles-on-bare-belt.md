# BUG-0859 — the live overlay drew every egg circle on bare belt: the frame JSON named a newer frame than the boxes

**Found** 2026-10-23, on `vpt-lenovo1` device3 ("Synthetic eggs"), while verifying BUG-0858 live.
**Reported by** the agent, from the live frame JSON and the capture it was attached to.

## What was wrong

The detector was right and the overlay still showed the circles beside their eggs.

The monitor's worker analyses **one** frame and its result is then attached to **every** frame's JSON
until the next analysis (`SampledWorkerAnalyzer`: the frame worker only notes the newest frame, the
work happens on the analyzer's own thread at `sample_hz`). So the JSON of capture N usually carries
the boxes of an **older** frame — and `captured_at` says so, which is why BUG-0836 could let the client
measure the age.

But the JSON's `filename` was the capture the JSON is *attached to*, not the capture the boxes were
*measured on*. And BUG-0836's frame-lock draws the picture the client fetches from `filename`
("show the capture the newest analysis was computed FROM"). So the client drew:

- the **newer** capture (up to one `sample_hz` period + one analysis time newer than the boxes), and
- the boxes of the **older** frame, on it.

On a belt the eggs move in that gap, so every circle ended up next to its egg instead of on it.
Measured live on the device3 line: the boxes of a JSON sat a **19.4 px median** (90th percentile
44.6 px, worst 96 px) from the detections of the capture the JSON was attached to, and **33 of 223**
circles had a mostly-blue interior — bare belt, not an egg. The client's own compensation does not
help: the eggs on this belt move 2-3 px/s, so only 20 of 223 observations carried a velocity at all,
and in frame-lock mode the boxes are deliberately NOT carried forward (there is no lag left to correct
once the picture is the analysed one).

## Fix

`SampledWorkerAnalyzer` now remembers the file name of the frame it analysed and `frame_record`
writes **that** name into `filename`, so it agrees with `captured_at` (the analysed frame's own
capture time). The client then shows the picture the boxes were measured on, and the circles are on
the eggs by construction — which is the whole promise of the frame-lock.

## Verification

- `tests/backend_host/test_egg_quality.py` — the JSON of a LATER capture names the EARLIER (analysed)
  frame, and a JSON written before any analysis still names its own frame.
- Live on `vpt-lenovo1`: the JSON's `filename` and its `captured_at` now point at the same frame, and
  the boxes sit on the eggs of the capture the client fetches (see the media in `SOURCES.md`).

## Not done

- The overlay is still a still picture that updates every ~12 s, not a live video. That is the cost of
  a 640x640 CPU forward on this host, unchanged by this fix.
- In **live** mode (the small switch in the corner) the boxes are carried forward by velocity, which
  is only right while the motion is constant. On a belt at 2-3 px/s that is close enough to be worth
  offering, but the frame-lock is the correct mode for checking the circles.

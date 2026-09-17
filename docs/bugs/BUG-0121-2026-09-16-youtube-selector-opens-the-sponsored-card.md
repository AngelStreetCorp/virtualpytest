# BUG-0121 — A feed selector opens the ad instead of the video

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0121                                                     |
| Reported  | 2026-09-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / userinterface                                 |
| Fixed in  | build 9151                                                   |
| Commit    | TBD                                                          |

---

## Symptom

`goto --userinterface youtube-android-mobile --node video_player` on a paired phone left
Chrome open on `swype.ch` and failed with:

```
Navigation failed at step 2 (home → video_player): verification failed -
Video did not appear (motion threshold: 3.0%)
```

The step's mosaic shows YouTube's home feed, then an advertiser's web page and a cookie
banner. The action itself reported SUCCESS — it clicked something, just not a video.

The report gave no way to tell which node it hit: the line read
`click_element(element_id=' seconds')`, a search term rather than an identifier, with a
green tick beside it.

## Root cause

Two independent things, both visible in dump 3 of the phone's `ui_dumps.txt`:

**The feed opens on a promoted card.** Above the fold there was exactly one video card and
it was an ad:

```
clickable Button     desc='Sponsored - After the season, Justin Murisier takes off …'
          ViewGroup  desc='7 minutes, 19 seconds'
```

`' seconds'` is how the tree says "a video card" — real cards carry their duration. The
sponsored card carries one too, so it matched, and `_best_match` (`phone_agent.py`) ranks
clickable nodes first, which is the ad's wrapping Button. Nothing in the selector could say
"not an ad": `|` had always meant OR, and there was no way to express an exclusion.

**Excluding the labelled node would not have been enough either.** The word "Sponsored" is
on the Button; the duration is on a *child* ViewGroup that says nothing about being an ad.
A selector that skipped only the node carrying the word would have fallen through to that
child and tapped the same card — `click_element_by_id` taps a node's bounds centre, which
is inside the ad.

The edge's retry action made the same mistake from the other direction:
`tap_coordinates(540, 796)` is a fixed point near the top of the feed, which is where the
promoted slot sits.

## Fix

**Selectors can exclude** (`features/mobile-app/backend_host/controllers/phone_agent.py`).
A term prefixed with `!` disqualifies a match, so `' seconds|!Sponsored'` reads "the first
thing with a duration that is not an ad". It stays one string, so it still fits an edge's
existing `element_id` parameter.

The exclusion is **by area, not by label**: every element carrying an excluded term
contributes its bounds to a blocked region, and any candidate whose tap point falls inside
one is dropped. That covers the ad's children without needing parent pointers — whatever is
drawn inside an excluded element belongs to it.

**The tree scrolls past the promoted slot first.** `edge-home-to-video_player` on
`youtube-android-mobile_navigation` is now `swipe_up` → `click_element(' seconds|!Sponsored')`,
with the same pair as its retry. The blind `tap_coordinates` retry is gone. The same
exclusion was added to the two `views` selectors (mobile and tablet search results).

**The report says what was clicked.** `click_element` records the node it landed on and
returns it as the action's message; `action_executor` appends a controller's own words to
the result after `" - "`, and `report_step_formatter` shows that tail beside the action.
`click_element(element_id=' seconds') ✓ clicked 'Sponsored - After the season…'` would have
made this bug obvious from the report alone.

**The traces ship with the run.** New `shared/src/lib/utils/ui_dump_capture.py` — the device
counterpart of `dom_capture.py`, process-global for the same reason (one execution is one
process), so no executor plumbing. `generate_and_upload_script_report` uploads this
execution's sections as `ui_dumps.txt` beside `execution.txt` and links them from the
summary bar as **🔍 UI dumps**, and from the verification review's Log Sources. The host
keeps its own cumulative file for reading over SSH.

## Verification

Replayed the real dump through the selector
(`_parse_selector` / `_blocked_regions` / `_best_match`):

- `' seconds'` picks the ad card — the shipped behaviour, reproduced.
- `' seconds|!Sponsored'` picks nothing on that screen, ad child included, so the edge falls
  through to its retry instead of opening an ad.
- With a real card present (`'Spaceship - 5 minutes, 25 seconds - Go to channel Kanye West'`),
  it picks the real card.
- `' seconds'` with no `|` is still passed through verbatim, leading space and all.

End-to-end on the phone (pending): `goto --userinterface youtube-android-mobile --node
video_player` should reach `video_player` with `WaitForVideoToAppear` passing, the report's
action line naming the video it opened, and a **🔍 UI dumps** link present only when a
selector actually missed.

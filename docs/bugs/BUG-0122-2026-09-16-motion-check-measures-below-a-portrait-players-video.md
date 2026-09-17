# BUG-0122 — The motion check measures below a portrait player's video

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0122                                                     |
| Reported  | 2026-09-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / userinterface                                 |
| Fixed in  | build 9151                                                   |
| Commit    | TBD                                                          |

---

## Symptom

`WaitForVideoToAppear` failed on a paired phone for a minute at a time, on a video that was
visibly playing and visibly captured:

```
Navigation failed at step 1 (home → video_player): verification failed -
Video did not appear (motion threshold: 3.0%)
```

The report's own evidence agreed with the failure — the saved motion crops were identical —
while the phone's stream, viewed at the same moment, showed the video running.

## Root cause

`detect_motion` defaults to the **centre 60%** of the frame when no `area` is given
(`DEFAULT_MOTION_AREA_FRACTION`, `video_analysis_helpers.py`). That default is written for a
TV: video edge to edge, with station and channel overlays round the outside that would
otherwise make a frozen picture read as motion.

A portrait phone is the opposite shape. YouTube draws its player across the **top ~28%** and
fills the middle of the screen with the title, Subscribe row and comments — all static. So the
default region sat entirely below the video and measured page furniture. On this phone's own
captures, while the video was playing:

| region | frame-to-frame change |
|---|---|
| centre 60% (the default) | **0.9 – 2.9%** |
| the player band (top) | **4.1 – 7.6%** |
| threshold in the tree | 3.0% |

Every centre sample was under the threshold and every player sample was over it.

`WaitForVideoToAppear` / `WaitForVideoToDisappear` could not be pointed anywhere else, either:
`detect_motion` has taken an `area` for a long time, but `_execute_video_playback_verification`
never read one from its params and `waitForVideoToAppear` had no parameter to forward. `area`
was reachable from `DetectMotion` and from nothing else.

**This bug is very good at looking like other bugs.** It cost most of a session in wrong turns,
and each one had corroborating evidence:

- The saved motion crop showed the page *below* the player with a black band at its top edge.
  Read as "the player is blanked", which led to **DRM** — MediaProjection does blank
  FLAG_SECURE surfaces, so the theory fitted. It was wrong: the crop was the centre region, and
  the black band was the letterboxed bottom edge of the player, not the player.
- Consecutive `capture_*.jpg` are often byte-identical, because the phone streams ~3 fps while
  ffmpeg writes captures faster. Read as "the capture pipeline has stalled". It had not;
  frames further apart differ.
- A relaunched YouTube shows an empty feed and an undrawn player for several seconds, which
  looks like both of the above.

Check which region the verification actually measured before believing any frame-level theory.

## Fix

`area` now reaches the playback verifications, which is all the plumbing that was missing:

- `video.py` — `waitForVideoToAppear` / `waitForVideoToDisappear` take `area` and forward it to
  `detect_motion` (which already accepted it), and name the region in their log line.
- `video_verification_helpers.py` — `_execute_video_playback_verification` reads
  `params['area']`, passes it, and records it in the result details. Both commands now declare
  an `area` param, so it is pickable in the UI like `DetectMotion`'s.
- `youtube-android-mobile_navigation` / `video_player` carries
  `area: {x: 0, y: 40, width: 631, height: 345}`.

Coordinates are in **capture** pixels, not device pixels: the 1080x2400 screen is streamed
scaled to 631x1280 and `detect_motion` crops the capture frame. `y` starts at 40 to leave the
status bar out, since a ticking clock is motion too.

## Verification

`goto --userinterface youtube-android-mobile --node video_player` on the paired Galaxy S21
Ultra, with the fix deployed:

```
VideoAnalysis: Motion restricted to area x=0,y=40,w=631,h=345
VideoAnalysis: Frame change: 11.9% (threshold: 3.0%)
VideoVerify:   Video appeared after 2.1s
🎯 Result: SUCCESS
```

11.9% against the same 3.0% threshold that had been reading under 3% for sixty seconds, and it
settles in two seconds instead of timing out.

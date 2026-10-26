# BUG-0906 — The egg line published a good/bad count that the picture cannot support

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0906                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | backend / monitoring                                         |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The egg line showed two counters: **Eggs** and a **good / bad / unverified** breakdown. The breakdown was the
problem. `egg_classify` grades a crop of a white egg lying on a blue belt in daylight, and that image carries **no
evidence at all** of what is inside the egg — the classifier is looking at a white blob. It duly reported **~99 % bad**,
because that is what the model says, and the profile published that number next to a real egg count with no
explanation.

Nothing on screen said "this number is meaningless". A demo that shows "Eggs: 214 / Bad: 212" reads as a quality
measurement, and it is not one: the same image would have graded a cracked egg and a fresh one identically.

## Root cause

`egg_quality_yolo_belt` (BUG-0870) inherited `egg_classify` from the two older egg profiles, and that stage was kept
for continuity: the counters are part of the block, so removing them would change the shape of the panel. The bug is
not that the grader is inaccurate — it is that an inaccurate grader is **published as a measurement**.

A grade on this feed is only possible with **candling**: the egg held against a light, where the shell shows its
interior. Nothing in the device3 camera feed does that.

## Fix

A new profile, `backend_host/config/monitor/profiles/egg_count_yolo_belt.yaml`, that **counts eggs and says nothing
about their condition**:

- the belt detector only — **no `egg_classify` stage**, so no good/bad verdict is computed at all;
- `events: egg_seen: {attr: label, in: [egg]}` fires **once per tracked egg** (when the track is finalised: it was seen
  twice, or it left the frame), so `count_total` is *distinct eggs*, not detections per frame;
- **no `ui.counters` block** and `box.colour_by: none` — there is no class to colour a circle by, and no second number
  that could be mistaken for a quality;
- `reset_counters: { every_s: 120 }` keeps the counter to "eggs in the last two minutes" for a demo, and the frame JSON
  carries `counting.since` so the client can say what the number covers;
- `votes: 2 / min_votes: 1` — an egg is counted on its second sighting (or when it leaves), which is what turns
  "detected in several frames" into "counted once".

`egg_quality_yolo_belt` stays, for the graded block, with its own disclaimer in the profile, in
`docs/agent/devices/MONITOR_PROFILES.md` and in BUG-0870. The operator chooses which one a device runs; what changed is
that the honest one exists and says what it does.

## Honest numbers

The count is a **detection** count. It counts what the model saw: on the measured ground truth of 147 eggs
(built without the belt model) the detector covers **98.6 %**, so a hundred counted eggs means about a hundred and a
half eggs passed. It says **nothing** about the interior of any of them.

## Verification

- `tests/backend_host/test_egg_count_belt_profile.py` — the manifest has no `egg_classify` analyzer, the event is
  per-track, the KPI is a plain count, there is no good/bad counter, and the file says the grade needs candling.
- The profile loads through `monitor.profiles.load_profile()` and passes `validate_manifest_light()`.
- Live on `vpt-lenovo1`: the counter rises with the eggs on the belt and no good/bad number is published.

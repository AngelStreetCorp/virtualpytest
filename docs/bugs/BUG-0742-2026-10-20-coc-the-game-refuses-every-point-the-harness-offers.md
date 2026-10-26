# BUG-0742 — The game refused every point the harness offered, so the battle was lost with 0 % damage

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0742                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Closed (live proof: the army leaves the tray in every battle) |
| Severity  | High                                                         |
| Area      | game / clash of clans (TASK-100)                             |
| Fixed in  | build 90145 |
| Commit    | see the merge commit                                          |

---

## Symptom

The run of 19:00 UTC won two battles with 100 % damage and 3 stars, so the deploy signal of
BUG-0725 works. The other battles of the runs of 19:00, 20:00, 21:00 and 22:00 tell the other
half of the story - the army never left the tray:

| run | step | the harness says | taps | outcome | damage | points the game refused |
|-----|------|------------------|------|---------|--------|--------------------------|
| 19:00 | 18 | no_deploy | 20 | defeat | 0 % | 5 |
| 19:00 | 32 | deployed | 76 | **victory** | **100 %** | 0 |
| 19:00 | 37 | deployed | 76 | **victory** | **100 %** | 0 |
| 19:00 | 50 | no_deploy | 36 | defeat | 0 % | 9 |
| 19:00 | 56 | no_deploy | 32 | defeat | 0 % | 8 |
| 20:00 | 10 | deployed | 95 | defeat | 35 % | 5 |
| 20:00 | 18 | deployed | 76 | **victory** | **55 %** | 0 |
| 20:00 | 36 | no_deploy | 40 | defeat | 0 % | 10 |
| 21:00 | 12 | deployed | 80 | **victory** | **100 %** | 1 |
| 22:00 | 9 | deployed | 79 | **victory** | **30 %** | 1 |
| 22:00 | 13 | deployed | 75 | **victory** | **57 %** | 0 |
| 22:00 | 17 | deployed | 76 | defeat | 12 % | 0 |
| 22:00 | 21 | deployed | 76 | **victory** | **56 %** | 0 |
| 22:00 | 26 | deployed | 84 | defeat | 47 % | 2 |
| 22:00 | 31 | no_deploy | 40 | defeat | 0 % | 10 |
| 22:00 | 36 | no_deploy | 36 | defeat | 0 % | 9 |

**16 battles, 9 defeats - and 6 of them with 0 % damage and the whole army still in the tray.**
The report says why, every time:

> deploy 1: 4 taps at (620, 275) deployed no troop, the game refused the point (the count badge
> did not move)

The game refuses a deploy point silently: no marker, no sound, the number on the card does not
move. The harness sees that and tries another point - and then gives up.

## Root cause

**1. The harness offered five points, all in the same patch of ground.** When the game refused the
plan point, the code shifted it by 50 px in four directions (`POINT_SHIFTS`) and tried those. A
plan that sat between the buildings of the base stayed between the buildings, so the whole clump
was refused: 5 refused points, 20 taps, 0 % damage, the army untouched. The refused points of the
run of 19:00 were 33 to 185 px from the Town Hall - and the planning prompt asked the model for
exactly that:

> Stay CLOSE to the buildings: roughly 60 to 200 px from the Town Hall, in the open grass right
> beside them

The points the game **did** take were 140 to 355 px from the Town Hall, on the open field around
the base: (913, 150) and (825, 195) in the run of 19:00, (643, 105) in the run of 20:00. The prompt
was pointing the model at the one zone where the game says no.

**2. The second try asked the model for a new point - and the model is slower than a battle.** The
planning call of those runs took 215.94 s, 236.5 s, 257.1 s and 172.67 s. A Clash of Clans battle
lasts 3 min. The re-plan therefore arrived long after the fight was over: the battle of the run of
20:00 at step 10 was lost at 35 % damage because the first clump was refused, the model thought
for four minutes, and the wave that finally landed had half a battle to work with.

Two more rules were measured and dropped, because the frames do not support them: the open ground
around the point (the share of non-grass pixels within 40 px) and the distance to the nearest
building. The points the game took score 0.036 to 0.370 on the first and 4.1 to 29.4 px on the
second, the points it refused 0.073 to 0.590 and 5.7 to 14.9 px - the ranges overlap, so neither
one is the rule. The rule the frames do show is the distance to the **Town Hall**, and the prompt
was aiming at the wrong side of it.

**3. A card without a number blocked every deploy.** `count_changed()` compares the badge box of
the card that was tapped with itself. When the card carries no number (the King, a spell, any card
whose count the game does not draw), the box is empty in both pictures, the difference is zero, and
the harness read that as "the count did not move" - the wave was reported as refused and the
harness moved on, point after point. The code only excused a card *beyond* the third slot, so a
King in the first slot blocked the whole army.

## Fix

`shared/src/lib/game/clashofclans/attack.py`:

* **20 points instead of 5.** `deploy_candidates()` builds the points to offer the game out of the
  plan point and the rings at 30, 60, 90, 120, 150, 190, 230 and 270 px around it, three points per
  ring - the roomiest ground of the ring first. The plan point keeps the first place, the
  neighbourhood is covered in order, and the list reaches out of the base.
* **The second try takes the next points of that list.** No model call happens inside a battle
  any more: a call that takes four minutes cannot help a fight that lasts three. The first try
  offers the points next to the plan, the second the rest of the neighbourhood.
* **A refused point costs 2 taps instead of 4.** Two troops are enough to move the number on the
  card, and a point the game refuses must not cost the army more than it has to.
* **The prompt asks for the open field just outside the wall.** The point must be plain grass
  **outside the base's wall ring**, on the side of the Town Hall, 10 to 50 px outside the wall so
  the troops reach the buildings in seconds, and at a gap in the wall when there is one. A point
  inside the ring is the one the game refuses; a point far out in the field is walked over under
  fire. Measured on the frames of the run of 23:00: the point of the victory (930, 280) lies right
  beside a wall gap, the point of the defeat (930, 224) against a closed wall.
* **An empty badge means "no signal".** A card that carries no number no longer blocks the wave.

## Tests

`tests/shared/test_clashofclans_attack.py` (40 tests, 4 new):

* `test_the_harness_offers_many_points_before_it_gives_the_battle_up` - the game refuses
  everything: the harness must try at least 8 points and still deploy no troop.
* `test_the_harness_does_not_ask_the_model_again_inside_a_battle` - the model is asked for a plan
  once, not once per try.
* `test_the_candidates_reach_out_of_the_base` - the list must spread, not stay in one corner.
* `test_the_roomiest_ground_is_offered_before_the_ground_between_the_buildings` - the open ground
  comes first.
* `test_a_card_without_a_count_does_not_block_the_wave` - an empty badge is no signal.

## Verification

* The whole Clash of Clans suite is green: 227 tests (40 attack, 187 of the rest of the game and
  the lease guard).
* Offline, on the frames of the runs of 19:00 and 20:00: the candidate list of the plan point
  (620, 275) - the point the game refused in the battle of step 18 - now offers 20 points spread
  from 30 to 270 px around it, the plan point first. **13 of the 20 sit 140 to 355 px from the
  Town Hall of that base**, which is exactly the zone the game took its points in (the refused
  points of that battle were 33 to 185 px away); for the plan point of the battle of step 50 it
  is 15 of the 20. The old list - the plan point and four spots 50 px away - could not leave the
  refused zone.
* Live: the next hourly run of the Pi must show a battle that is no longer lost with 0 % damage
  and the whole army in the tray. The run log of every battle is
  `/var/lib/vpt/coc_frames/llm/<run_id>_report.html`.

## Live proof - the run of 23:00 UTC on the new code

`468598fd-545c-41b7-a2ca-721b3959f84a`, four battles, every one of them on the new code:

| step | the harness says | taps | refused points | where the army came out | outcome | damage |
|------|------------------|------|----------------|---------------------------|---------|--------|
| 12 | deployed | 95 | 9 | (470, 390) | defeat | 0 % |
| 16 | deployed | 76 | 0 | (930, 280) | **victory** | **89 %** |
| 31 | deployed | 91 | 7 | (911, 404) | defeat | 15 % |
| 35 | deployed | 76 | 0 | (930, 224) | defeat | 8 % |

**Four battles, four deploys, no battle lost with the army in the tray.** On the old code that
happened in 6 of the 16 battles of the runs of 19:00 to 22:00. The battle of step 12 is the proof
of the fix: the game refused nine points, the harness went on to the next ones of its list and the
army came out - the old code would have given up there and the battle would have been lost with
0 % damage and 75 troops in the tray.

The run itself ended at step 38 with `RuntimeError: no screenshot from the device (adb)`: the phone
stopped answering the screenshots, not the harness.

**What the frames say about the rest of the defeats.** The army leaves the tray now, but the base
still holds it in 3 of the 4 battles. The frames show why, and the rule is visible: the point the
game takes is always **outside the wall ring** - the point of the victory (930, 280) lies on the
open grass right beside the wall, where the wall has a gap and the troops walk straight in, while
the point of the defeat (930, 224) lies against a closed wall next to the builder's hut, and the
troops are shot down on the wall. The planning prompt therefore asks now for the grass **just
outside the wall** (10 to 50 px), at a gap when there is one, and never inside the ring - a point
inside the ring is the one the game refuses.

The rest is the base against the army: 14 deployed battles so far, 8 victories (30 % to 100 %
damage) and 6 defeats, and the wins and the losses are decided by the base - the two 100 % wins
were against bases whose right flank was open, the 8 % loss against a base with four inferno
towers behind a closed wall.

## Live proof - the run of 00:00 UTC on the refined prompt

`1cfe7b39-7378-4773-a550-e2604334cb18`, 63 steps, stopped at the step limit. One battle, won:

| step | the harness says | taps | where the army came out | outcome | damage | stars |
|------|------------------|------|---------------------------|---------|--------|-------|
| 39 | deployed | 76 | (910, 346) | **victory** | **52 %** | **2** |

The point lies in a **gap in the wall** on the right flank of the base, on the open grass right
beside it - exactly what the prompt asks for since the fix: the grass just outside the wall, at a
gap when there is one. The Town Hall of that base is 330 px away, the wall in front of the point
is broken, and the troops walked straight in: 2 stars, 52 % damage, 4 troops left in the tray.

The run spent most of its steps waiting for the army to be trained ("Army is full at 15/15"), so
one battle is thin evidence - the runs of 19:00 to 23:00 fought 1 to 7 battles each.

## Live proof - the run of 01:00 UTC on the refined prompt

`f1f87211-9d3a-4ebb-b4ac-731d46e83cde`, 68 steps, stopped at the step limit. Two battles, **two
victories**:

| step | the harness says | taps | refused points | where the army came out | outcome | damage | stars |
|------|------------------|------|----------------|---------------------------|---------|--------|-------|
| 35 | deployed | 76 | 0 | (883, 116) | **victory** | **100 %** | **3** |
| 57 | deployed | 79 | 1 | (960, 315) | **victory** | **67 %** | **1** |

The battle of step 57 shows the whole chain working: the model planned (1040, 300), the code
nudged it to (930, 295) and moved it off the building to (930, 285) - the game **refused** that
point - and the next point of the candidate list, (960, 315), took the army.

**The three runs on the new code: 7 battles, 7 deploys, 4 victories** (the run of 23:00 with the
first prompt: 4 battles, 4 deploys, 1 victory; the runs of 00:00 and 01:00 with the wall-gap
prompt: 3 battles, 3 victories, 52 %, 100 % and 67 % damage). On the old code 6 of the 16 battles
of the runs of 19:00 to 22:00 were lost with the whole army in the tray - that mode is gone.

**All seven runs together: 23 battles, 11 victories, 12 defeats.** The army left the tray in 17 of
the 23 battles; the 6 battles it did not leave it in are the 6 of the old code, and it left it in
every single battle of the new code.

**What is still open.** The game draws a thin orange line around the village, and every point the
game took lies on that line or just outside it, while every point it refused lies between the
buildings. The line is not a closed curve - it is a mesh of diagonals - so a flood fill of the
outside does not separate the two (tried on the frames of all eleven known points: the fill
trapped itself and called every point "inside"). The rule the harness uses is therefore the one
the frames support: never inside the base, and as close to the wall as the game allows.

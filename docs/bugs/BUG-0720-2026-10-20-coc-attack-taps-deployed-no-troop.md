# BUG-0720 — The CoC attack harness spent 140 taps on a point the game refused and deployed no troop

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0720                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / clash of clans (TASK-100)                             |
| Fixed in  | build 90145 |
| Commit    | see the merge commit                                          |

---

## Symptom

Half of the battles of the hourly CoC run end **with the whole army still in the tray and 0 %
damage**: the harness taps 140 times and not one troop comes out.

Run `a5e2ce36` (2026-10-20, 12:00 UTC, report `a5e2ce36-a917-4c26-94a2-c527bf6cc136_report.html`)
played six battles:

| battle | deploy point | outcome |
|--------|--------------|---------|
| 1 | (900, 180) | **no_deploy** - 140 taps, 70 troops left, defeat 0 % |
| 2 | (330, 143) | **no_deploy** - 140 taps, 71 troops left, defeat 0 % |
| 3 | (937, 285) | deployed - 70 taps, 7 troops left, defeat 31 % |
| 4 | (916, 369) | deployed - 71 taps, 4 troops left, victory 97 %, 1 star |
| 5 | (780, 408) | **no_deploy** - 140 taps, 70 troops left, defeat 0 % |
| 6 | - | deployed - 70 taps, 1 troop left, victory 100 %, 3 stars |

The same thing happened in the run of 11:00 UTC (`3e0ca7e8`): both battles, `no_deploy`, 0 %.

## What the evidence says

The game **refuses** the deploy silently and the harness **cannot see it**.

* The refusal is silent: in the video of the 11:00 run (`rec_chunks/3e0ca7e8_000.mp4`, frames
  `000_120` at 11:02:04 to `000_147` at 11:02:31) the battle is running the whole time
  ("Battle ends in: 2M 55S" down to "2M 28S"), the troop card **is** selected (the Barbarian card
  gets its white border at 11:02:14), the taps land on open grass, and **nothing appears on the
  field**: the pixels around the plan point change by 3 grey levels (compression noise) and the
  tray still reads `x59` in every frame.
* The camera does **not** move when the battle starts: the scouting frame and the battle frame
  have the same geometry (the plan frame of the 11:00 run matches the battle frame with a mean
  difference of 2.07), so the plan point is still the point the taps are made on. The earlier
  "the camera zooms in" theory is **disproved** - the point is not moving under the taps.
* The point is not obviously wrong either: the plan points of the three refused battles sit on
  grass, 2-15 px away from the nearest building, the same distance as the points of the three
  battles that worked. A grass check cannot tell the two groups apart.
* The harness never notices, because **its only check is a model call** that reads the troop
  numbers on the tray of the battle screen - the screen the code already knows the model reads
  wrong (run 33caf775: 59 Barbarians read as 59, then 59 again where the card said 21). The run of
  12:00 reads "71 of 70 troops left" for an army of 70: a mistake of one is invisible against a
  threshold of 75 % of the army, so the harness concludes "nothing came out", asks the model for
  another point, gets another bad point, and taps 140 times.

## Root cause

**The harness has no way to tell that a deploy landed.** It fires the whole army at one point and
then asks the model, from a picture the model misreads, whether the army left the tray. When the
answer is wrong the harness repeats the same mistake: the same clump, the same bad point, another
140 taps. A refused point costs a whole battle.

## Fix

The picture is the free signal: a troop that appears on the grass changes the pixels around the
plan point, a refused tap does not.

* `field_changed()` (new, in `shared/src/lib/game/clashofclans/attack.py`) compares the frame
  before a batch of taps with the frame after it, in a 140 x 140 box around the plan point, and
  reports whether the ground changed. It costs no model call and no money.
* The deploy now taps a small batch (4 taps), looks at the field, and only then sends the rest of
  the wave. A refused point costs 4 taps instead of 70.
* When the game refuses a point, the harness tries the **next point around it** (50 px to the side,
  no model call) before it asks the model again. A model call costs ~35 s and money; a point
  50 px away is another patch of ground.
* The decision "did the deploy land?" no longer depends on the model reading the tray: the count
  is still read for the report, but the loop is driven by the picture.
* When every point is refused the harness says so in the report (`the game refused the point`)
  and stops, instead of spending the whole army on a point the game does not take.

The zoom theory that briefly justified a second plan on a battle frame is removed: the camera
does not move, so the plan point of the scouting frame is the point of the battle.

## Tests

`tests/shared/test_clashofclans_attack.py`:

* `test_the_field_check_sees_a_troop_and_ignores_an_unchanged_field` - the check sees a troop and
  ignores an unchanged field.
* `test_a_deploy_that_puts_no_troop_on_the_field_is_retried_with_another_point` - a refused point
  is retried at the next point, and the troop lands there.
* `test_a_battle_where_the_game_refuses_every_point_gives_up_instead_of_tapping_140_times` - the
  harness gives up instead of spending the army.
* `test_the_deploy_check_costs_no_model_call` - the check is free.

# BUG-0725 — The CoC attack harness dropped its army on a building roof and its deploy check believed the field had changed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0725                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Closed                                                      |
| Severity  | High                                                         |
| Area      | game / clash of clans (TASK-100)                             |
| Fixed in  | build 90145 |
| Commit    | see the merge commit                                          |

---

## Symptom

The 14:00 UTC run (`218ca432-e474-42dc-afe8-29aab1be4afc`) played three battles and lost all three
with **0 % damage, 0 stars, defeat** - while the report of every battle says the troops were
`deployed`:

| battle | deploy taps | troops left | outcome |
|--------|-------------|-------------|---------|
| 1 | 79 | 76 | defeat, 0 % |
| 2 | 103 | 11 | defeat, 0 % |
| 3 | 79 | 76 | defeat, 0 % |

Not one troop ever left the tray: the count badge of the Barbarian card reads `x59` in every frame
of every battle.

## What the evidence says

* **The plan point was a roof.** Battle 1 was planned at `(700, 370)`. On the battle frame of that
  very run (`rec_chunks/218ca432-e474-42dc-afe8-29aab1be4afc_003.mp4`, frame 125 at 14:00:22) that
  pixel is `(89, 81, 79)` - the grey roof of the dark elixir storage, not grass. A troop only comes
  out on open ground; the game takes the tap on a building and says nothing.
* **The card was armed.** The same video shows the white selection border around the Barbarian card
  from frame 289 of the chunk, so the taps were not sent with an empty hand.
* **The check that should have noticed it lied.** `field_changed()` (BUG-0720) compares the frame
  before the taps with the frame after, in a 140 x 140 box around the plan point. During a fight the
  field moves all the time - troops walk, buildings burn, the camera shakes - so the box always
  changed and the harness always concluded "the deploy landed". That is why the report says
  `deployed` and the battle ends at 0 %.
* **The honest signal is the number on the card.** Measured on the frames of run `33caf775`
  (2026-10-20, 09:00 UTC, where troops did come out): the Archer card goes `x11` -> `x10` -> `x9`
  while the wave lands, **162 to 556 pixels of the badge move**, and a card that deploys nothing
  keeps its badge **pixel-identical** (0 pixels over hundreds of frames, armed or not).
* **Arming a card moves the badge too - the timing keeps it out of the comparison.** An armed
  card rises a pixel or two and the other card dims: 80 to 366 pixels of the badge move, as much
  as a real count change (measured at 10 fps on the winning battle of run `bcaa97d8`). That
  animation lasts **0.4 s**, and the picture that opens the comparison is taken only after the card
  has settled (`CARD_SETTLE_S = 1.2 s`), so the arming never falls inside it.
* **The card-selection change is what the old "tray band" idea measured.** Comparing the whole
  badge band of the tray (x 175-430) jumps by 0.05 to 0.28 of the band when the *selection* moves
  from one card to the next - with the number unchanged. A wide band cannot tell a count change
  from a selection change.

## Root cause

Two separate mistakes, one after the other:

1. **The deploy point was never checked against the ground.** `validate_point()` only knows the
   layout (the HUD, the troop tray, the distance to the base centre). It cannot tell a roof from
   grass, and the model regularly points at a building: the run of 12:00 UTC refused three of six
   battles on points that sit 2 to 15 px away from the nearest building, which the game refuses
   silently.
2. **The deploy check measured the wrong thing.** "The ground around the plan point changed" is not
   evidence that a troop came out, because the ground moves all the time during a fight. The
   harness therefore believed every tap and sent the whole army (59 taps) into a refused point.

## Fix

`shared/src/lib/game/clashofclans/attack.py` now decides with two signals that cannot lie, both
taken from the picture and both free (no model call, no money):

* **`is_grass()` / `grass_spot()`** - the ground under the plan point must be open grass
  (yellow-green, never grey, blue or brown; measured on the real frames of run `218ca432`). A plan
  that lands on a building is moved to the open grass next to it (up to 40 px, inside the deploy
  band); a plan with no grass around it is sent back to the model with the reason. The check runs
  twice: on the planning frame and again on the battle frame, right before the taps.
* **`count_changed()`** - the count badge of the card that was tapped must move. A troop that left
  the tray changes its number; a refused tap leaves it alone. The badge box is the 37 x 15 px of
  the digits themselves, and the picture that opens the comparison is taken after the card has
  settled, so neither the selection border nor the rise of the card can fake a count change.

`field_changed()` is gone. When the count badge does not move, the harness says so in the report
(`the game refused the point`) and tries the next point around it, as it already did for BUG-0720.

## Tests

`tests/shared/test_clashofclans_attack.py` (36 tests):

* `test_the_count_badge_sees_the_number_move_and_ignores_an_unchanged_card` - the badge signal.
* `test_the_ground_check_sees_grass_and_refuses_a_roof` - grass is grass, a roof is not.
* `test_a_point_without_any_grass_around_it_is_not_used` - no grass, no point.
* `test_a_plan_on_a_roof_is_moved_to_the_open_grass` - the plan is moved off the roof.
* `test_a_plan_without_any_grass_is_asked_again` - the model is asked again, with the reason.
* `test_a_card_without_a_count_does_not_block_the_wave` - the King and the spells have no badge
  to read, so they never block the wave.
* `test_the_deploy_check_waits_for_the_card_to_settle` - the picture that opens the comparison is
  taken after the card has settled, so the arming cannot read as a count change.
* `test_a_deploy_that_puts_no_troop_on_the_field_is_retried_with_another_point` and
  `test_a_battle_where_the_game_refuses_every_point_gives_up_instead_of_tapping_140_times` - the
  refusal is seen and the army is not spent on it.

## Verification

* Offline, on the recorded frames of the real runs:
  `x11 -> x10 -> x9` gives `count_changed = True`, an idle pair gives `False`, the refused battle
  of run `218ca432` gives `False` for every frame pair, and the refused plan point `(700, 370)`
  gives `is_grass = False` with the nearest grass 20 px away at `(700, 390)`.
* **The grass rule cannot make the harness refuse every point.** Measured on the 320 battle
  frames of the three recorded runs (`bcaa97d8`, `218ca432`, `33caf775`), every frame the
  harness would fight on has grass in the deploy band - **none without**, the share of grass
  running 60 % to 66 % - so the plan always has open ground to move to.
* **The badge signal separates a wave from a refusal.** Compared over the code's own window
  (1.2 s, the settle) between frames in the same selection state: the refused battle of run
  `218ca432` shows **no** badge change at all while the fight runs (its only 12 changed pairs
  are the end-of-battle transition, frames 276-287), while the genuine wave of run `33caf775`
  shows 72 changed pairs in a row (frames 157-228).
* **Live: the run of 19:00 UTC fought five battles on the new code** (`ff3606fe-11f9-4b21-be02-
  e27cc0f22460`, 80 steps, 19:00:06 to 19:34:16):

  | step | the harness says | taps | troops left | outcome | damage | stars |
  |------|------------------|------|-------------|---------|--------|-------|
  | 18 | no_deploy | 20 | 75 | defeat | 0 % | 0 |
  | 32 | **deployed** | 76 | 28 | **victory** | **100 %** | **3** |
  | 37 | **deployed** | 76 | 7 | **victory** | **100 %** | **3** |
  | 50 | no_deploy | 36 | 76 | defeat | 0 % | 0 |
  | 56 | no_deploy | 32 | 76 | defeat | 0 % | 0 |

  Two battles dropped the army and **won with 100 % damage and 3 stars**. In the first of them
  the model planned on a building and the harness moved the plan onto the open grass next to it:

  > plan nudged: point too far from the base (950, 145) -> (913, 160); plan moved
  > (913, 160) -> (913, 150): the point was on a building, the open grass is next to it

  ... and the wave landed there (76 taps, 28 troops left, victory, 100 %, 3 stars). The second
  battle took the plan as it was (825, 195) and won the same way.

  The three battles the game refused say so, with the point that was tried and the reason:

  > deploy 1: 4 taps at (620, 275) deployed no troop, the game refused the point (the count
  > badge did not move)

  That is the difference to the run of 14:00, where the old code called those battles `deployed`
  and spent 79 to 103 taps on them (3/3 battles "deployed", 0 % damage). Now the report says
  `no_deploy` with the reason, and the army is not spent on a refused point: those battles used
  20 to 36 taps, not 79 to 103.

* **The ground and the badge, read on the frames of that very run.** The report of the run keeps
  the picture of every step, so the picture the harness planned on can be read again:
  * the badge of card 0 is the badge of the Barbarian card and reads **x59** there (the Archer
    card of card 1 reads **x16**) - the two boxes `COUNT_BOXES` reads hold the real digits (178
    and 151 white pixels);
  * the plan point of the winning battle (913, 150) is **open grass** (187, 177, 64), and the
    point it was moved from (913, 160) is **not** (162, 127, 63) - that is why the harness moved
    it, and the wave landed on the grass;
  * the plan point of the second winning battle (825, 195) is **open grass** (160, 178, 66) and
    was taken as the model gave it.

* **The badge of the winning battle, frame by frame.** On the recorded chunk of that battle (554
  battle frames, 946 to 1499) the badge of card 0 crosses the threshold 17 times: three small
  moves while the card is armed (14 to 55 px, frames 946 to 960) and then, from frame 1111 to
  1136, the jump of the real wave - **368 to 391 px** on 12 of those 14 pairs (281 and 93 px on
  the last two), the number of the card falling as the troops left the tray. Nothing else on the
  whole fight crosses the threshold.

* Live: the run log of every battle is `/var/lib/vpt/coc_frames/llm/<run_id>_report.html`.

# BUG-0713 — The Clash of Clans attack harness deployed during the battle countdown, then tapped the army three times over

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0713                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / clash of clans vision-llm player (TASK-100)           |
| Fixed in  | build 90145 |
| Commit    | `66d150f8a`                                                  |

---

## Symptom

The `game_clashofclans_llm` script attacks, but the battles it fights are lost or barely scratched. Over 65 live
battles the damage told the story: a battle that the harness filled with **130 deploy taps or fewer** ended at
**100 % damage** most of the time, a battle with **170 taps or more** ended at **0-29 % damage** and was usually a
defeat. A single battle was seen with 208 taps for an army of 70 troops, and it ended at 29 % damage after four
minutes. The run report showed the same shape: `battle deployed: 207 deploy taps in 4 passes, troops left 55`.

## Root cause

Two separate faults in `shared/src/lib/game/clashofclans/attack.py`, both invisible in the report because the report
only shows the outcome:

1. **The harness deployed during the scouting countdown.** `play()` hands any frame with the red Surrender button to
   the attack harness. That frame is the *scouting* screen, which shows `Battle starts in: 29s`. A tap on the ground
   during that countdown places a marker and deploys nothing. The first deploy wave was therefore spent on a screen
   where no troop can come out, and the plan itself (one model call) plus the count read (a second call) had already
   eaten most of the countdown.

2. **The deploy was a treadmill.** After each deploy pass the harness re-read the troop tray with the model and
   deployed whatever the model said was left. The tray number only drops when a troop is *deployed*, never when one
   dies, so a reading that did not change sent the harness round the loop again: up to `MAX_PASSES = 4` passes of
   `MAX_TAPS_PER_CARD = 40` taps each. The measured result was 208 taps for a 70-troop army, four passes, and three
   extra model calls per battle - roughly 90 s of the 3 min battle spent tapping at a ground that was already decided.

Both faults push the same way: the army arrives late, in waves that land on top of each other, while the defenses
shoot it. The measured correlation between the tap count and the damage is the visible symptom.

A third, smaller fault: after the harness taps **Next** to skip a walled base it planned the next base on the frame
it already had, before the new village had finished loading.

## Fix

`shared/src/lib/game/clashofclans/attack.py`:

- `is_battle_started()`: a new pixel check on the dark **Overall Damage** panel in the bottom-right, which appears
  as soon as the battle is running. Measured on real frames: 0.06-0.10 dark pixels while scouting, 0.21-1.00 during
  the battle, threshold 0.15. `_wait_for_battle_start()` waits for it before the first deploy tap, so no wave is spent
  on the countdown. If the panel never shows (a mode without it) the deploy goes ahead as before; if the battle has
  already ended the step reports `battle_ended` instead of deploying into nothing.
- **One** read of the tray, on the **scouting** frame, and one deploy wave per card, `MAX_TOTAL_TAPS = 140` as a hard
  cap. The scouting frame is the one place where the model reads the tray right: on the busy battle screen it read
  `x21` as `59` again, and that is what sent the deploy round the loop. The second read is kept for the report
  (troops left) and never deploys anything again.
- `WAVE_GAP_S = 8`: the ranged wave (Archers, King) lands after the tanks have walked and pulled the defenses.
- `_wait_for_next_base()`: after **Next**, the harness waits until the orange Next button is back on screen, so the
  next village is planned on its own frame.
- The plan prompt no longer asks for a point "above y=400" - the model read that as the bottom edge of the screen, 250 px
  from the buildings, so the troops walked the whole field under fire. It now asks for grass 60-200 px from the Town
  Hall, on its side of the base.

## Verification

- Unit tests (`tests/shared/test_clashofclans_attack.py`, 25 tests): the harness waits for the battle to start before
  the first tap, reads the counts on the scouting frame, deploys the army exactly once (59 Barbarians + 11 Archers +
  1 King = 71 taps), keeps the total under the cap, leaves a gap between the waves, waits for the next village after
  a skip, deploys anyway when the damage panel never shows and does not deploy into a battle that already ended. The
  whole CoC suite is 64 tests.
- Offline replay of the real battle of run `33caf775` (the real frames, the plan and the tray counts the model actually
  answered): **208 taps / 6 model calls before, 71 taps / 3 model calls after** - the same battle, the same inputs.
- Live verification on the phone (run `d1ca7ecd`, 2026-10-20 08:00 UTC): the harness now deploys **one wave of
  71 taps in 1 pass** where the old code needed 173-207 taps in 4 passes, with 3 model calls per battle instead
  of 6. The deploy itself did not take, though: both battles ended at 0 % damage with the whole army still in
  the tray. Two causes are visible in the frames: the first plan point landed on the base's wall (a tap on a
  wall deploys nothing) and the second battle started before the taps went in. The harness now checks the tray
  after the deploy and, when the army did not leave it, asks for another point and deploys again
  (`MAX_DEPLOY_ATTEMPTS` = 2); the plan prompt asks for open grass away from walls, roofs and paths.

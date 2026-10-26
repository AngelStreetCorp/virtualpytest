# BUG-0705 — Pokémon runner shuffles between two squares at the door of Blaine's gym

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0705                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | see the merge `pokemon-cinnabar-quiz`                        |

---

## Symptom

Run `20261019-201708` (host-clone-1) got the Secret Key, entered Cinnabar Gym (166) and stalled `no_progress` on
`volcano_badge` at (16, 8): no event at all for 5 minutes after `gym_leader`. A local replay of the canonical save walked
(16, 8) <-> (15, 8) for 189 ticks, all `walk`.

## Root cause

Blaine (3, 3) stands in the last of six rooms shut by gates; each gate opens on a right answer at a quiz machine (a wrong
one starts the battle with the trainer behind it, beating him opens it). `runner.goal_action` (`_badge` branch) only knew
Lt. Surge's barrier: it called `talk_at(Blaine)`, `walk` found no path, and `overworld.toward` stepped greedily west into
the wall below the first machine and back.

## Fix

`runner.cinnabar_quiz`: in Cinnabar Gym with the leader out of reach (A* with sprites not blocking), walk to the square
below the nearest machine in reach not answered yet (`CINNABAR_QUIZ`), face it, press A and answer OUI / NON from
`CINNABAR_QUIZ_YES`. After `QUIZ_IDLE_TICKS` ticks with no machine in reach and Blaine still shut off, all are asked again.
Guard test: `test_cinnabar_gym_walks_to_the_quiz_machine_in_reach_when_blaine_is_behind_the_gates`.

## Verification

Replay of the stalled save (300 s): six `gym_quiz` events in machine order 0-5, every answer right (no quiz battle), then
the battle with Blaine (CANINOS 42, PONYTA 40). On the host: the cleared run moves past (16, 8).

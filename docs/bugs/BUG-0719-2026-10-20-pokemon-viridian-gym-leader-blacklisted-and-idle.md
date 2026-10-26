# BUG-0719 — Pokémon runner blacks the Viridian gym's leader out of its gym and stands still for ever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0719                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | —                                                            |

---

## Symptom

Host run `20261020-134355` (host-clone-2) stalled `same_spot` on the milestone `earth_badge` in the Viridian City
gym (map 45), at (6, 8): **the same square for 300 ticks**. The run's log ends with the runner standing still:

```
not_the_leader  t=1792496707.33  picture=23  at=[2, 1]
said = ["J.uis le", "J.uis le ROI du / KARATE! Ton      .",
        "KARATE! Ton / destin repose    .", "destin repose / entre des main"]
battle_choice   t=1792496721.04  kind_battle=trainer  enemy_level=38
battle_end      t=1792496897.30  outcome=lost  battle=trainer  turns=17
defeat          t=1792496897.36
...
stalled         t=1792497762.24  reason=same_spot  milestone=earth_badge  map=45  pos=[6, 8]
```

A local replay of the same save (`test_scripts/game/local/pokemon_play_local.py`) reproduces it exactly:

```
{"ticks": 562, "counts": {"talk": 1, "text": 27, "not the leader": 1, "at goal": 533},
 "milestone": "earth_badge", "map": 45, "pos": [6, 8]}
```

**533 "at goal" ticks**: the runner had nobody left to talk to and stood still. The diagnosis is
`~/vpt-private/pokemon/stalls/stall_latest_20261020-134355.diagnosis.md`.

## Cause

Two defects in `shared/src/lib/game/pokemon/runner.py`, both in the rule that tells a gym leader from a passer-by.

**1. The answer was judged while the game was still writing it.** BUG-0718's rule reads the pages the game showed
after the runner talked to somebody and, when none of them holds a trainer's battle line ("GIOVANNI veut se battre!"),
concludes that the person is not the leader (`runner.py:2175-2187`). But a gym leader's **speech** comes first and his
battle line comes after it. The runner read the speech while the game was still typing it — the last page was cut in
the middle of a word, *"destin repose / entre des main"* — and the battle line was never read. The verdict
"no 'veut' in the answer ⇒ not a trainer" cannot tell *"he is not a trainer"* from *"his battle line has not been
typed yet"*.

The log proves the verdict was wrong: **the battle started anyway**, 13 s later, against a trainer of level 38 —
Giovanni's team. The runner lost that fight (`battle_end outcome=lost`, `defeat`), and by then the real leader was
blacklisted for good.

The same rule fired a second time on text that did not belong to the person at all: the experience messages of the
fight that had just ended (*"FLORIZARRE gagne 219 points .EXP!"*) were still in the answer buffer and were taken for
the answer of the next person the runner talked to (`not_the_leader` at t=1792497217.0, picture 14 at [10, 1]).

**2. The blacklist had no way back.** `memo["not_leaders"]` is a permanent list; `is_person()` (`runner.py:2196-2201`)
refuses every square in it and `gym_leader()` filters it out. One wrong verdict about the leader emptied the gym:
`goal_action` found no candidate at all and returned `"at goal"` on every tick until the stall detector stopped the
run. The canonical save shows the end state — `not_leaders` holds **eleven** squares, the real leader `[2, 1]`
among them.

## Fix

* **The answer must settle before it is judged** (`Runner.answer_settled`). The runner waits until the game has been
  quiet for a while (18 s without a new page, 40 s after the talk at the latest) before it decides that somebody is
  not a trainer. A leader's battle line has the time to arrive; when a battle does start, the answer buffer is
  cleared and no verdict is taken at all.
* **The runner challenges the leader instead of only talking to him** (`Runner.challenge`). A gym leader answers
  with a plain line when the runner talks to him (*"Tu ne pourras accéder à la LIGUE POKéMON... seulement en
  battant notre CHAMPION!"*) — in Gen 1 only his line of sight starts the fight. While the answer waits, the runner
  walks onto the square the leader looks at (below him first, then his sides) and lets the game decide.
* **A battle proves the person is a trainer** (`Runner.forget_not_leader`): the person the runner talked to last
  comes out of the blacklist as soon as a battle starts. The game does not lie about a trainer, so the runner can
  never keep a trainer out of the gym.
* **The text of a battle is not an answer to a talk**: the answer buffer is emptied when a battle starts, so the
  experience messages of a fight are never taken for the answer of the next person.
* **A gym never runs out of candidates**: when every candidate has been judged "not the leader", the runner forgets
  the blacklist (it is a memory of one visit) and starts again instead of standing still.

Two guard tests in `tests/shared/test_pokemon.py`:
`test_a_gym_leader_is_never_blacklisted_on_a_speech_that_is_still_being_written` and
`test_a_gym_that_has_no_candidate_left_never_stands_still`.

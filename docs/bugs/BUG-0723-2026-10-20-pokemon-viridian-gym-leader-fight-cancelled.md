# BUG-0723 — Pokémon runner cancels the Viridian gym's leader fight and blacks him out of his gym

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0723                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | game / pokemon runner (TASK-33)                              |
| Fixed in  | build 90145 |
| Commit    | —                                                            |

---

## Symptom

Host run `20261020-153325` (host-clone-1) stalled `same_spot` on the milestone `earth_badge` in the Viridian City
gym (map 45), at (6, 8): **the same square for 300 ticks**. The run's own log is only 0.08 s long — the stall
counters of the previous run were still in the memo, so the detector stopped the run on its first tick — and it
ends with the gym's blacklist being emptied:

```
strategy          t=1792503221.98  trigger=resumed after a stop
leaders_forgotten t=1792503222.06  milestone=earth_badge  forgotten=11
stalled           t=1792503222.06  reason=same_spot  milestone=earth_badge  map=45  pos=[6, 8]
```

The run that really stalled is `20261020-134355`; the diagnosis of this stall is
`~/vpt-private/pokemon/stalls/stall_latest_20261020-153325.diagnosis.md`.

A local replay of the canonical save with the code of `main` (BUG-0719 included) shows what the runner does with
the gym's leader — **it blacks him out with his own speech as the evidence, and no fight ever happens**:

```
{"ticks": 434, "counts": {"talk": 1, "text": 15, "answer pending": 28, "not the leader": 1, "walk": 389},
 "milestone": "earth_badge", "map": 45, "pos": [4, 13], "party": 5, "stalled": null}

not_the_leader  {'milestone': 'earth_badge', 'picture': 23, 'at': [2, 1],
                 'said': ['Tu ne pourras / acc.der . la     .', ..., 'battant notre / CHAMPION!', ...]}
```

Picture 23 at (2, 1) is the gym's leader (Giovanni). Once he is in the blacklist, `goal_action` finds no candidate
and the runner stands still for ever.

## Cause

`shared/src/lib/game/pokemon/runner.py`, the rule that tells a gym leader from a passer-by
(`goal_action`, `runner.py:2187-2208` and `Runner.challenge`, `runner.py:2251`).

**1. The runner moved while the game was talking to the leader.** BUG-0719's rule answered a leader who did not
show a trainer's battle line by *stepping into his line of sight* while his answer was still coming
(`challenge()` was called on every tick of an unanswered talk). In Gen 1 a step cancels the trainer's script: the
leader's speech starts again from the first page and the fight — which the game starts from that script — never
comes. The replay above shows it: the leader's speech is read **twice** (`said` holds the pages twice, with an
empty page between), the runner ping-pongs around him for 28 ticks ("answer pending"), and no battle is fought in
200 s of play.

**2. The leader was judged as soon as his answer settled.** The fight comes from the leader's own script, about
13 s after the talk — run `20261020-134355` shows it: the leader's text was read at t=1792496707.3 and the trainer
battle (level 38, Giovanni's team) started at t=1792496721.0, **13.7 s later**, while the runner was already
walking away. So the runner had to stay still and let the script run; instead it judged the leader "not the
leader" on the strength of his own pre-battle speech and put him in the blacklist, which emptied the gym.

**3. The challenge could not do its job anyway.** The runner usually stands on the square the leader looks at
already — it walked there to talk — and `challenge()` skipped that square (`target == here`), so the player never
*entered* the leader's line of sight; the game only checks the sight when the player moves.

## Fix

* **No step while the game is talking** (`goal_action`): while the answer has not settled, the runner waits. A
  gym leader's fight comes from his own script, ~13 s after the talk; a step would cancel it.
* **The leader is challenged when the game is quiet** (`goal_action` + `Runner.challenge`): once the game has been
  quiet for a while and no fight came, the runner steps into the square the leader looks at (the one below him) —
  and when it already stands there, it steps aside, so that coming back on it enters the leader's line of sight.
  The challenge is tried `GYM_CHALLENGE_TRIES` (3) times before the person may be judged.
* **Only then is the person judged** (`goal_action`): the verdict on a person comes after the challenge, never
  before, so the leader is never blacklisted while his fight can still come.

Guard test in `tests/shared/test_pokemon.py`:
`test_a_gym_leader_is_not_judged_while_the_game_is_talking_and_is_challenged_after`. The two older gym tests
(BUG-0718, BUG-0719) were updated to the new order: wait while the game talks, challenge when it is quiet, judge
afterwards.

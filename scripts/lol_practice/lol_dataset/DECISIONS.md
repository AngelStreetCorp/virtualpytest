# Decision points: runtime keys, labels and rewards

Built by `lol_dataset/jev_cut.py` from the tables. Two layers, cut like the runtime coach (`coach_policy.py`):

- **coach**: every 5 s, the next 5 s decide the label (options: farm_safe, push, freeze, fight, avoid, recall_now).
- **tactician**: every 3 s, the next 3 s decide the label (options: follow_plan, hold_back, hold, e_now).

## Runtime key status (state keys of `build_view`)

`available` = filled from the tables. `null-in-replays` = a replay can never carry it (spec section 9). `null-for-now` = the
tables could carry it later (calibration, absolute HP, turret detector, the ready flag).

| key | status |
|---|---|
| `time` | available |
| `level` | available |
| `hp` | available (fraction; absolute from the detector state) |
| `gold` | null-in-replays |
| `cs` | available |
| `ad` | available |
| `items` | available (Live Client, subject only) |
| `enemies` | null-for-now (absolute HP and map-unit distance need calibration and HP per type; enemy champion identity not built) |
| `ally_minions_near` | available (count of ally minions within 150 screen px of the subject) |
| `ready.q` | null-for-now (rows carry the cooldown seconds, not the ready flag) |
| `ready.e` | null-for-now (rows carry the cooldown seconds, not the ready flag) |
| `ready.r` | null-for-now (rows carry the cooldown seconds, not the ready flag) |
| `turret_d` | null-for-now (no turret detector) |
| `turret` | null-for-now (no turret detector) |
| `map.x` | null-for-now (no screen-to-world calibration) |
| `map.y` | null-for-now (no screen-to-world calibration) |
| `map.zone` | null-for-now (no screen-to-world calibration) |
| `next_enemy_turret` | null-for-now (no turret detector) |
| `plan.mode` | null-for-now (the previous plan label is not recorded yet) |
| `plan.reason` | null-for-now |

## Labels (rules, first match wins)

Coach: recall_now (recall event in window) > avoid (hp < 50 % and >= 15 % max HP lost) > freeze (hp < 50 % and damage) >
push (hp >= 70 %, >= 2 CS, no damage) > farm_safe (default). `fight` is in the option list but no rule fires for it yet:
it needs the enemy laner's HP, which the replay tables do not have.

Tactician: hold_back (>= 10 % max HP lost) > e_now (E cast in window with >= 3 ally minions within 150 px) >
hold (no movement, no CS, no damage) > follow_plan (default).

Every label carries a confidence (0.4 default, 0.5-0.6 when a rule fires) and its rule name.

## Rewards (owner table, per 1 s slice from the slice's own HP; attributed to the chosen label only)

| term | value | status |
|---|---|---|
| last hit | +1 | available (CS step matched to a minion death) |
| cannon last hit | +2 | null-for-now (minion type is the wave rule; not used in the sum yet) |
| champion kill | +10 | available (Live Client) |
| assist | +3 | available (Live Client) |
| turret kill | +12 | null-for-now (no turret detector) |
| death | -10 | available |
| damage taken | -0.01 per HP | available (HP of each slice from the slice's own start) |
| missed last hit | -0.5 | null-for-now (needs the killable-minion model) |
| idle next to a killable minion | -0.2 per tick | null-for-now (needs the killable-minion model) |

## Self-check numbers (from the 5 Hz build of game 8018174981)

- 222 decision points; every chosen option is in its option list.
- Coach: 78 farm_safe, 5 push, 0 freeze / avoid / recall_now / fight. Tactician: 115 follow_plan, 14 hold, 9 hold_back, 1 e_now.
- Baseline: always farm_safe is right on 35 % of coach points.
- Label agreement on 20 hand-labelled points: not done yet (needs the video frames and a human-style read of each window).

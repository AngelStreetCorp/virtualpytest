# BUG-0871 — The Pokémon's battle moves were billed to a paid model, so a free run was not free

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0871                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Pokémon's lane is free — its strategist is on MiniMax M3.1 Flash — but the runs still cost money. The
platform's own call log shows a second model on the same lane:

```
usage_key     profile   model                calls  cost
text.decision jev       typesafe/jev-1.13     254   $0.007989
```

Every **battle move** was decided by Jev, a paid model (~$0.0026 a fight, the game's documentation says). The
owner asked for the runs to play on Flash and to cost $0; half of the Pokémon's model calls were not.

## Root cause

`test_scripts/game/game_pokemon.py` had two battle choosers: `heuristic` (no model at all) and `jev` (the paid
decision model). The chooser is pinned by name:

```python
resolution = router.resolve_profile("jev", "text.decision", team_id)
```

`resolve_profile` pins one profile and consults no route, so the `text.game_strategy` route (Flash) never
reached the battle decisions. The dispatcher asked for the paid one explicitly:

```python
PARAMS = f"--save {SAVE} --userinterface pokemon-blue-web --max_duration {MAX_DURATION_S} --chooser jev"
```

## Fix

- `test_scripts/game/game_pokemon.py` — the chooser is now `model_choose(profile, …)`, with `jev_choose` and a new
  `flash_choose` on top of it. `flash_choose` pins **`minimax-m3-1-flash`** for `text.decision`. The profile has
  **no fallback**, so a throttled or failing call returns `{}` and the runner falls back to the heuristic for that
  turn — a free run never pays for another hop. `--chooser` accepts `heuristic|jev|flash`.
- `scripts/agent/pokemon_dispatch.py` — the volume lane asks for `flash` (`POKEMON_CHOOSER`, default `flash`);
  the dataset deployment keeps `jev` (`POKEMON_CHOOSER=jev`).

## Verification

- `python3 -m pytest tests/scripts/test_pokemon_dispatch.py tests/shared/test_pokemon.py -q` — 181 passed, including
  `test_flash_choose_pins_the_free_profile_for_the_decision_calls` (the chooser pins `minimax-m3-1-flash` for
  `text.decision`) and `test_the_volume_lane_plays_with_the_free_chooser` (the lane's default is `flash`, and
  `POKEMON_CHOOSER=jev` still works).

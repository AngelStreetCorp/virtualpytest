# BUG-0864 — The free model lane stopped at the first rate limit and the games never played again

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0864                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | ai / games                                                   |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Clash of Clans Flash run started and died 21 seconds later, on its very first model call:

```
09:33:10 coc-flash: started game/game_clashofclans_llm.py on vpt-pi1 (task f87041e1, lease bcaa83b5)
09:33:31 The test ran and reported a failed result
```

The call log says why — every Flash call of the day answered `rate_limit`:

```
usage_key             minute  ok  error_type   calls  cost
vision.game_coc_flash 09:33   f   rate_limit      1  $0.00
```

and the whole profile did not answer once between 08:00 and 09:40:

| Hour | Flash calls | answered | rate limited |
|------|-------------|----------|--------------|
| 05:00 | 60  | 60 | 0  |
| 06:00 | 213 | 213 | 0  |
| 07:00 | 174 | 174 | 0  |
| 08:00 | 100 | **0**  | **100** |
| 09:00 | 16  | **0**  | **14** |

The Pokémon's strategist call failed the same way (09:16:06, `text.game_strategy`, `MiniMax-M3.1-Flash-Preview`,
`rate_limit`) and the run sat in a menu for 25 minutes without playing again.

## Root cause

Two things, both about what a 429 means.

1. **The caller treated a throttle as a fatal error.** `shared/src/lib/game/clashofclans/llm_player.py` ended the
   run at the first failed call (`stop = "api_error"`), and the CoC script's own retry loop only knew three
   transient errors (`Connection error`, `gateway unreachable`, `timed out`) — a rate limit was not one of them.
   The Pokémon's strategist had no retry at all.
2. **The gateway gave up on the first 429 too.** `shared/src/lib/ai/gateway.py` walks the fallback chain on error,
   but a rate-limited hop was simply left behind: the request was refused, so nothing was billed, yet the call
   was lost. The free model was never asked again.

The account behind the free plan is shared with the paid models of the same provider: the Atlas job made 1685
calls in the 08:00 hour (320 in the 07:00 hour) and its own direct MiniMax calls were refused too — it only kept
working because it falls back to OpenRouter, which is paid. The free lane had no way to wait for its turn.

## Fix

A free model that the provider throttles is waited for; a metered one is not.

- `shared/src/lib/ai/prices.py` — `is_free(hop)`: a hop is free when its endpoint is a flat plan (the MiniMax
  coding plan), a local endpoint, or its price row is zero.
- `shared/src/lib/ai/gateway.py` — a hop that answers HTTP 429 and is free is **retried on the same hop**
  (`AI_RATE_LIMIT_RETRIES`, default 3, with the backoff `AI_RATE_LIMIT_BACKOFF_S`, default 5 s / 20 s / 45 s).
  A metered hop is not retried: its caller moves on to the fallback chain as before.
- `shared/src/lib/game/clashofclans/llm_player.py` — a step whose call was rate limited is **skipped, not fatal**:
  the run notes it, waits two seconds and plays on (`_rate_limited()`).
- `test_scripts/game/game_clashofclans_llm.py` — the script's own retry loop now knows a rate limit is transient.
- `test_scripts/game/game_pokemon.py` — the strategist asks again (4 attempts, 5 s apart) before the run falls
  back to its fixed rules.

Nothing of this costs money: a refused request is never billed, and the free profile has no paid fallback.

## Verification

`python3 -m pytest -q tests/shared/test_flash_lane_resilience.py` — 10 passed (a free hop is free, a metered hop
is not, a throttled step is skipped and the run goes on, another API error still ends the run).

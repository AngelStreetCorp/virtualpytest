# BUG-0931 — A run whose model stayed throttled held the phone for an hour

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0931                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                      |
| Area      | games / clash of clans player                                 |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/task164-throttle-gives-the-phone-back`       |

---

## Symptom

The free route refused every call of the CoC runs of **2026-10-26 03:00 and 04:00**:

```
RuntimeError: AI router: minimax: rate limited (HTTP 429), retrying in 5s;
               minimax: rate limited (HTTP 429), retrying in 20s; …
```

Each of those runs made **258 refused calls** and held `vpt-pi1/device1` for **56 minutes**. The runs
cost nothing — the free plan is free, no fallback was bought — but while they held the phone, the other
lane (the free CoC lane that plays every 30 minutes) found the device busy at every slot, so the game
did not play for two hours.

The whole of the platform's MiniMax traffic of those hours was throttled; the lane's own runs of
01:03 and 02:03 (40 and 46 calls, all answered) and of 05:00 and 06:00 were fine.

## Root cause

**A throttled step was skipped, and the run went on — step after step, until its budget ran out.**

`shared/src/lib/game/clashofclans/llm_player.py` skips a step the provider refused with HTTP 429
(nothing was billed, so the game should keep playing — 2026-10-23). The skip was correct for a blip,
but nothing stopped it from becoming a habit: the run skipped 60 steps in a row, each one after the
retry ladder (5 s, 20 s, 45 s), until the notional budget stopped it at 60 steps. That is the 56
minutes.

The game cannot play without an answer, so the run was holding a device for nothing.

## Fix

`shared/src/lib/game/clashofclans/llm_player.py`

- `MAX_RATE_LIMITED_SKIPS = 3` — a throttle that lasts three steps in a row ends the run with
  `stop = "api_error"` and the reason *"the model was rate limited 3 steps in a row: the phone is
  given back"*. The phone goes back in about two minutes instead of an hour.
- A step that the model answers resets the counter: a single throttle (a blip) still only skips that
  step, as before.

## Verification

- `pytest -q tests/shared/test_clashofclans_llm.py` → **47 passed**, three of them new: a run whose
  model stays throttled ends after three steps and gives the phone back, one throttled step does not
  end the run, and a throttle after a good step counts from zero again. The first one fails without
  the fix (the old behaviour ends the run with `max_steps` after 60 skipped steps).

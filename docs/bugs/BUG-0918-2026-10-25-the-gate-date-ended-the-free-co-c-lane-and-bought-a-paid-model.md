# BUG-0918 — The gate date ended the free CoC lane and bought a paid model instead

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0918                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | games / ai routing                                           |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The CoC lane stopped playing and started costing money, on the same day, for the same reason.

- **Nothing played.** The extra CoC job (`coc-flash`, the free lane between the hourly runs) logged
  `tick: coc-flash: past 2026-10-25` **every minute**: the job's own `until` date had arrived, so the
  dispatcher refused to start it.
- **The money went somewhere else.** The hourly deployment `CoC LLM hourly` has no `--model_choice`, so it
  takes `auto` — and `auto` had been reading *"Flash before 2026-10-25, Claude Haiku 5.5 from then on"*. From
  2026-10-25 on, the hourly CoC runs were served by the **paid** `claude-haiku-5-5`: 508 calls and
  **$0.150** on 2026-10-25 alone (`ai_calls`, `usage_key`/`script_name` = the CoC player).

The task the lane serves is explicit about the money: *"every model call of the volume work runs on MiniMax
M3.1 Flash … A run must cost $0."*

## Root cause

**A date that was never a real deadline was written into the code as one.**

The Flash plan was understood (owner, 2026-10-19) as *"free on the flat coding plan until 2026-10-25"*, and
the date was baked into three places:

- `test_scripts/game/game_clashofclans_llm.py` — `FLASH_UNTIL = date(2026, 10, 25)`; `choose_model("auto")`
  returned Flash while `today < FLASH_UNTIL` and the **paid** Haiku afterwards.
- `scripts/agent/game_dispatch.py` — the `coc-flash` job carried `"until": "2026-10-25"`, the day the job
  stops starting.
- `shared/src/lib/ai/usages.py` — the usage key's own description told the reader the Flash route *"ends on
  2026-10-25"*.

Nothing re-checked the assumption, because a date is not a fact that announces itself. The owner's own
statement had already contradicted it on 2026-10-23: *"M3.1-Flash is unlimited (free) and MiniMax M3
restarts every 5 hours: we are not exploiting the system at its maximum."*

The two halves of the bug are the same date seen from two sides: the free lane was **switched off** on the
day the plan was supposed to end, and the paid model was **switched on** the same day. The lane did not stop
working — it changed vendor and started billing.

## Fix

- `test_scripts/game/game_clashofclans_llm.py` — `choose_model("auto")` is **always** Flash. The gate date is
  gone; the paid Haiku is reachable only when the run asks for it explicitly (`--model_choice haiku`). A paid
  model is a deliberate choice, never a silent one.
- `scripts/agent/game_dispatch.py` — the `coc-flash` job has **no end date** (`until: None`). It plays as long
  as the lane is enabled.
- `shared/src/lib/ai/usages.py` — the usage key says what it is: the free plan, used by every run that does
  not ask for a paid model.

The money is now safe by construction rather than by date: the Flash profile has **no paid fallback**, so a
Flash failure fails the run (free) instead of buying another model's answer.

## Verification

- `python3 -m pytest -q tests/scripts/test_game_dispatch.py tests/shared/test_clashofclans_llm.py` → **66
  passed** (two guard tests: `auto` is Flash on every day of the year, and the `coc-flash` job starts on a day
  far past the old gate date).
- On the live lane: the dispatcher's `plan` line reports `until -` for `coc-flash` and the job starts again;
  the CoC player's `ai_calls` show `MiniMax-M3.1-Flash-Preview` at `$0.000000`.

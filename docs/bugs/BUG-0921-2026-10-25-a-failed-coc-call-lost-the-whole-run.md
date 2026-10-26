# BUG-0921 — A failed CoC call lost the whole run: "Unexpected error: 'outcome'"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0921                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                      |
| Area      | games / clash of clans player                                 |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The hourly CoC run of 2026-10-25 20:00 **played for 27 minutes and was then thrown away**:

```
21:26:11 AI #46 step: anthropic/claude-haiku-5-5 in 980 out 375 19095 ms
21:26:11 AI #47 step: none in 0 out 0 9 ms FAILED
21:26:11 AI #48 step: none in 0 out 0 11 ms FAILED        (and so on to #52)
21:27:55 ❌ [game_clashofclans_llm] Unexpected error: 'outcome'
```

The row said only `Script execution failed` — the real reason (a `KeyError` on `'outcome'`) was in the
host's journal. The run reached its report, and **the report killed it**: 623 screenshots, a 34 MB
video and 27 minutes of play, all for a row that says "failed".

## Root cause

**A step that carries no outcome crashed the report builder.**

The attack harness builds its own step when it raises (`llm_player._fight`), and that step had no
`"outcome"` key — every other step has one. The report then read it with a hard lookup:

```python
def _outcome_text(step):
    o = step["outcome"]      # KeyError: 'outcome'
```

`_goal_line` right above it already did the safe thing (`step.get("outcome") or {}`); the helper it
calls did not. So one failed call — the kind every long run has — took the whole run down at the very
last step.

## Why the calls failed in the first place

The 46 steps before the crash were served by **`anthropic/claude-haiku-5-5`** — the **paid** model.
The `auto` model choice had turned paid on 2026-10-25 (BUG-0918), 46 paid steps burnt the run's
`--run_budget_usd 0.05`, and the meter then refused every call in a few milliseconds. On Flash the
run costs **$0** and the budget is never reached, so the run plays all its steps (as it did on
2026-10-23: *"40 steps, max_steps, budget $0.0158 → ok"*).

So the two faults sat on top of each other: the paid model emptied the budget, and the first refused
call killed the run.

## Fix

- `shared/src/lib/game/clashofclans/llm_report.py` — `_outcome_text` reads the outcome with
  `step.get("outcome") or {}`: a step without one is shown as *unknown*, not crashed on.
- `shared/src/lib/game/clashofclans/llm_player.py` — the failure path of the attack harness gives its
  step the outcome every other step has (`{"result": "unknown", ...}`), so the data is complete
  whatever the report does.

## Verification

- `python3 -m pytest -q tests/shared/test_clashofclans_llm.py` → **44 passed**, two of them new: the
  report survives a step without an outcome, and a failed attack step carries one. Both fail without
  the fix.

# BUG-0853 — The CoC budget meter charged a free model like a paid one

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0853                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | ai / game                                                    |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

A CoC run on MiniMax M3.1 Flash — an **unlimited free plan** model — reported a spend:

```json
"budget": {"run_spent": 0.024857400000000005, "month_spent_after": 3.92,
           "daily_allowance": 1.5, "day_remaining_after": 1.39}
```

The real cost of the same run was **$0** (`ai_calls.cost` = 0.000000 for 1816 Flash calls in 24 h).
The daily allowance is $1.50, so about 60 free runs a day would have been refused with
`budget_refused` — the meter would have stopped the free work it was supposed to allow.

## Root cause

`shared/src/lib/game/clashofclans/llm_budget.py` resolves the price of the model it runs on:

```python
ENDPOINT = "anthropic"
row = prices.price_for(ENDPOINT, model, rows=rows)
if not row or row.get("model") != model:
    raise PriceMissing(...)
if p_in <= 0 or p_out <= 0:
    raise PriceMissing("... has a price <= 0 ...: refused")
```

`ai_prices` had no row for `MiniMax-M3.1-Flash-Preview`, and `prices.price_for` fell through to
another model of the same endpoint (`claude-haiku-5-5`, $0.10 / $0.50 per Mtok) — so every Free
token was billed as a Haiku token. The second half of the bug made the fix impossible: a price of
**zero** was refused as "not a usable price", so a free model could not be priced as free.

## Fix

- `ai_prices` carries an explicit **0 / 0** row for the free model (`anthropic` and `minimax`,
  `MiniMax-M3.1-Flash-Preview`), with a note that it is the owner's unlimited plan.
- `llm_budget.resolve_price()` accepts a price of zero (a known free plan) and refuses only a
  missing or **negative** price. The "exact model row" rule is unchanged.

Guard test: `tests/shared/test_coc_llm_budget_price.py` (a free model costs 0, a paid model is
still priced, a missing row and a negative price are still refused).

## Verification

`python3 -m pytest -q tests/shared/test_coc_llm_budget_price.py` — 5 passed. Measured against the
live price rows: `resolve_price("MiniMax-M3.1-Flash-Preview")` → `0.0 / 0.0`, a 60-step run costs
`$0.000000` (it used to be $0.0249), and `claude-haiku-5-5` still costs $0.0004 a call.

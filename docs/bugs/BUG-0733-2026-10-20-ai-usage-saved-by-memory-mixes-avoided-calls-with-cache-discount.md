# BUG-0733 — "Saved by memory ≈ $13.98" pairs a count of avoided calls with a prompt-cache discount

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0733                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                        |
| Area      | frontend / backend                                           |
| Fixed in  | build 90145 |
| Commit    | `d5289bf` (deployed 2026-10-21, build 89471)                |

---

## Symptom

On `/monitoring/ai-usage` → **Efficiency**, the tile reads:

> **Saved by memory** — **1,128** — **≈ $13.98**

Next to it, the same tab says the platform spent **$2.37** on 4,285 useful requests. The page is
therefore claiming to have saved almost **six times** what it spent — a figure that decides the
"is the AI worth it" question, stated with no basis.

The same number is also drawn as a **gold bar stacked into the volume chart** ("Useful, wasted and
saved, by feature"), so a bar's length is no longer a number of requests.

## Root cause

`cost_saved` is not the price of the avoided calls. From the aggregator:

```python
avg_cost   = (b["cost"] - b["cost_wasted"]) / useful if useful and b["priced"] else None
saved_cost = (b["saved"] * avg_cost if avg_cost is not None else 0.0) + b["cache_saved"]
# shared/src/lib/ai/usage_view.py:167-172
```

So `cost_saved` = *(avoided calls × the average price of an answered call in that group)* **+ the
prompt-cache discount**. The two terms come from different populations, and the tile presents them
as one number.

Measured on the live 24 h window, per category:

| Category | avoided calls | `cost_saved` |
|---|---|---|
| `script_creation` | **0** | **$13.357169** |
| `discard_incident` | 1,116 | $0.018812 |
| every other category | 0 | < $0.0003 |
| sum of the category rows | **1,128** | **$13.38** |
| page total (`overview.totals.cost_saved`) | **1,128** | **$13.98** |

**The tile is not the sum of its rows.** `overview()` runs `_finish()` on each category and on the
page-wide bucket (`usage_view.py:201`, `:216`): the total prices the 1,128 avoided calls at the
page-wide average answered call ($2.370226 / 4,288 = $0.000553 → **$0.62**), dominated by Sonnet
script creation; the `discard_incident` row prices them at its own average (→ **$0.019**). So the
tile is $13.36 (cache) + $0.62 (avoided) = $13.98, the rows $13.38.

**95.5 % of the $13.98 (≈ $13.36) is the prompt-cache discount, almost all on `script_creation`, a
category with zero avoided calls.** The 1,128 avoided calls come from `discard_incident`; the tile
prices them at $0.62, their own category at $0.019.

The label is also wrong on its own terms: the tile says "Saved by **memory**", but the money is
mostly the **prompt cache** (`cache_saved`, accumulated at write time), and the calls were avoided
by a cache or a rule, not by memory.

Two further consequences:

- the Efficiency tab's stacked bar adds `saved` — a counterfactual for calls that never left — to
  `useful + wasted`, so **the bar total exceeds the request total**. On the live window:
  4,288 + 416 + 1,128 = **5,832** against 4,704 actual requests, a 24 % inflation
  (`shared/src/lib/ai/usage_view.py:178-185`);
- the CSV export writes `saved_cost` per row on the same basis, so the export and the screen agree
  with each other and both carry the mislabelled value.

## Fix

**Fixed 2026-10-21 by the TASK-147 redesign** (overview → provider/feature → call): the *Saved by memory* tile and the stacked bar are gone. Avoided calls show as their own count (*Avoided*, "answered by a rule") on the feature that has them; no money figure mixes them with the prompt-cache discount.

Not implemented in this task (TASK-147 is a content review). The proposed direction is in
`docs/tasks/TASK-147/SUGGESTIONS.md` §3 and §4:

1. **Split the number in two**, each with its own name and its own population:
   *Avoided by cache or rule* — 1,128 calls (a count) and *Prompt cache saved* — $13.36 (money).
2. **Drop the "≈"** and say how the money is derived ("what the avoided calls would have cost at
   today's prices").
3. **Stop stacking the counterfactual into the volume bar** — either give it its own row, or plot
   it as a separate series with its own scale.

## Verification

1. Open the Efficiency tab and check that the two numbers in the tile refer to the same population.
2. Sum the per-row `saved` of the "Useful, wasted and saved, by feature" chart and compare it with
   the tab's own request total — they must be equal, or the chart must state that it is not a
   request count.
3. Export the CSV for the same period and confirm the exported `saved_cost` matches the screen and
   is labelled the same way.
4. Check that a category with zero avoided calls (e.g. `script_creation`) cannot contribute to an
   "avoided calls" figure.

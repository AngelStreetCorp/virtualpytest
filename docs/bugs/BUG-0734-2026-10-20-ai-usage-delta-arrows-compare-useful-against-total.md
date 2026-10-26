# BUG-0734 — The "vs previous" arrows on the Overview compare a useful-only value against a total baseline

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0734                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                      |
| Area      | frontend / backend                                           |
| Fixed in  | build 90145 |
| Commit    | `d5289bf` (deployed 2026-10-21, build 89471)                |

---

## Symptom

On `/monitoring/ai-usage` → Overview, two of the four tiles carry a comparison arrow:

> Requests answered **4,285** — **▼ 39 %**
> Cost **$2.37** — **▼ 81 %**

Neither arrow is like-for-like:

| Tile | Current value | Compared against |
|---|---|---|
| Requests answered | `overview.totals.useful` = 4,288 | `previous.calls` — the **total** calls of the previous window |
| Cost | `overview.totals.cost_useful` = $2.370226 | `previous.cost` — the **total** cost of the previous window |

The current side excludes the wasted calls and the wasted spend; the baseline includes them. A
period with an unusual number of failures therefore moves the arrow even when the useful work did
not change at all.

Two smaller symptoms of the same code:

- the comparison window is never named — the reader cannot tell whether "▼ 39 %" means the previous
  24 hours, the previous day or the previous week;
- the **Tokens** tile reserves a footer slot for a comparison it never has and renders it empty
  (`OverviewTab.tsx:105-108`), and the mobile layout drops the arrows altogether
  (`MobileOverview.tsx:62-67`).

At the **30 d** period the problem becomes worse: the previous window falls outside the rollup's
history, so `previous` comes back all zeros and the arrows disappear with no explanation.

## Root cause

`report['previous']` is built by `previous_totals`, which copies the **total** fields out of the
aggregate of the preceding window:

```python
TOTAL_FIELDS = ("calls", "errors", "cost", "priced_calls", "tokens_in", "tokens_out")
# shared/src/lib/ai/usage_view.py:17

def previous_totals(previous_rows, group_by, hours, filters, now):
    totals = usage_report.aggregate(previous_rows, group_by, hours=hours, filters=filters, now=now)["totals"]
    return {f: totals[f] for f in TOTAL_FIELDS}
# shared/src/lib/ai/usage_view.py:58-60
```

The Overview tiles compare that against **useful-only** current values:

```ts
const answered = ov ? ov.totals.useful : totals.calls - (totals.errors ?? 0);
const cost     = ov ? parts(ov.totals, 'cost') : totals.cost ?? null;
// frontend/src/components/aiUsage/OverviewTab.tsx:55-64
```

`parts(ov.totals, 'cost')` resolves to `cost_useful`.

The previous window itself is the immediately preceding window of the same length
(`usage_view.split_periods`, `server_ai_routing_routes.py:635-639`), which is the right choice —
but the page never says so.

## Fix

**Fixed 2026-10-21 by the TASK-147 redesign** (overview → provider/feature → call): the arrows compare like with like: total calls and total cost of the period against the previous period of the same length (`previous.calls`, `previous.cost`), "↓ 50 % vs previous".

Not implemented in this task (TASK-147 is a content review). The proposed direction is in
`docs/tasks/TASK-147/SUGGESTIONS.md` §4: compare like with like (useful against useful, total
against total), name the window in the footer ("vs the previous 24 hours"), and either give the
Tokens tile a comparison or drop the reserved slot.

## Verification

1. Compare the Overview's `▼ 39 %` with the same quantity computed by hand from the previous
   window's `useful` — they must match.
2. Do the same for the `▼ 81 %` cost arrow against the previous window's `cost_useful`.
3. Read the footer: it must name the window it compares against.
4. Switch to "30 d": if no comparison is possible, the tile must say so instead of showing nothing.

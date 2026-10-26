# BUG-0731 — The Overview and the Usage tab show two different totals for the same period

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0731                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                        |
| Area      | frontend / backend                                           |
| Fixed in  | build 90145 |
| Commit    | `d5289bf` (deployed 2026-10-21, build 89471)                |

---

## Symptom

On `/monitoring/ai-usage`, period "24 h", with no other filter:

| Where | Label | Value |
|---|---|---|
| Overview, tile 3 | `Cost` | **$2.37** |
| Usage tab, Total row | `Cost` | **$2.45** |

Two tabs, one period, one word, two numbers. The same split appears in the other tiles:

| Where | Label | Value |
|---|---|---|
| Overview, tile 1 | `Requests answered` | **4,285** (useful only) |
| Usage tab, `Request` column | `Request` | **4,704** (every call) |
| Overview, tile 2 | `Tokens` | **15 M** (`tokens_useful` = 14,646,566) |
| Usage tab, Total row | `Token` | **15 M** (`tokens_in + tokens_out` = 14,752,279) |

## Root cause

The two tabs read different fields of the same response.

The Overview tile uses the **useful-only** figures:

```ts
const answered = ov ? ov.totals.useful : totals.calls - (totals.errors ?? 0);
const cost     = ov ? parts(ov.totals, 'cost') : totals.cost ?? null;
// frontend/src/components/aiUsage/OverviewTab.tsx:55-64
```

where `parts(ov.totals, 'cost')` resolves to `cost_useful`. The Usage tab's Total row uses the
**total**:

```tsx
total.cost
// frontend/src/components/aiUsage/UsageTab.tsx:211
```

The response carries both, and they differ by the wasted calls:

```
totals.cost                = 2.447277     <- useful + wasted
overview.totals.cost       = 2.447277
overview.totals.cost_useful= 2.370226
overview.totals.cost_wasted= 0.077051
```

`cost_useful + cost_wasted == totals.cost` holds exactly (2.370226 + 0.077051 = 2.447277), so the
two tiles are each internally correct and together inconsistent. Nothing on either tab says that
one of them excludes the wasted calls.

The same split affects "Requests": `overview.totals.useful` = 4,288 against `totals.calls` =
4,704, and "Tokens": `tokens_useful` = 14,646,566 against `tokens_in + tokens_out` = 14,752,279.

Two smaller consequences of the same split:

- the **Efficiency** tab reads `report.overview` only, while the Overview tab falls back to
  `report.totals` (`OverviewTab.tsx:58` vs `EfficiencyTab.tsx:55`) — on a server that does not send
  the overview block the two tabs show different things;
- the **CSV export** writes the raw grouping key and the totals but **no useful/wasted split**, no
  `cost_saved` and no `tokens_saved`, so it cannot reproduce either screen
  (`shared/src/lib/ai/usage_report.py`).

## Fix

**Fixed 2026-10-21 by the TASK-147 redesign** (overview → provider/feature → call): one cost everywhere: the *Spend* tile and every provider and feature use the total cost (`totals.cost`), the same figure the lists sum to.

Not implemented in this task (TASK-147 is a content review). The proposed direction is in
`docs/tasks/TASK-147/SUGGESTIONS.md` §3 and §4: pick **one** set of headline numbers (total spend
and total requests, with the answered/unusable split shown beside them), use it on every tab, and
make the CSV export carry the same split.

## Verification

1. Open `/monitoring/ai-usage` with the 24 h period and compare the Overview *Cost* tile with the
   Usage tab's Total row — they must be equal, or each must say what it excludes.
2. Do the same for *Tokens* and for the request count.
3. Export the CSV for the same period and check that its total equals what the Overview tile shows.
4. Repeat with the Result switch on "Wasted" and on "Useful": the tiles must state the basis of
   the number they show.

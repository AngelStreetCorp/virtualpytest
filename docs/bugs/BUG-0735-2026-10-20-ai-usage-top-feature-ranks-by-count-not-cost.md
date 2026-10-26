# BUG-0735 — "Top feature" ranks by request count, so it names the cheapest feature on the page

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0735                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                      |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `d5289bf` (deployed 2026-10-21, build 89471)                |

---

## Symptom

On `/monitoring/ai-usage` → Overview, the fourth tile reads:

> **Top feature** — **Showcase / games** — **1,536 requests**

That feature is the **cheapest** large consumer on the page. From the Usage tab, live, 24 h:

| Feature | Model | Requests | Cost |
|---|---|---|---|
| Showcase / games | MiniMax M3.1 Flash | 1,517 | **$0.00** |
| Script creation | Claude Sonnet 5 | 121 | **$1.48** |
| Browser agent | o4-mini | 68 | $0.31 |
| Ask AI | MiniMax m2.7 Highspeed | 53 | $0.18 |

`Script creation` alone is **$1.48 of the $2.45** the page says was spent — 60 % of the bill — and
the tile that is supposed to point at the expensive thing names the one that costs nothing.

A user deciding where to cut finds the tile actively misleading: it sends them to a 1,536-request
feature worth two cents instead of a 121-request feature worth $1.48.

The same tile also mixes two vocabularies: "Top **feature**" is a **category**
(`Showcase / games`), while the Usage tab's **Feature** column and the Calls tab's **Feature**
column are the **usage key** (`eval.text.decision.m…`). Two different things, one word.

## Root cause

The tile takes the category with the most *useful calls*:

```ts
const top = [...(ov?.categories ?? [])].filter((c) => c.useful > 0).sort((a, b) => b.useful - a.useful)[0];
// frontend/src/components/aiUsage/OverviewTab.tsx:62
```

and renders its name with a request count:

```tsx
label: t('Top feature'),
value: top ? categoryLabel(top.key, t, names) : '—',
footer: <Line>{top ? tn(top.useful, '{count} request', '{count} requests', ...) : ' '}</Line>,
// frontend/src/components/aiUsage/OverviewTab.tsx:116-118
```

Nothing in the aggregation ranks by cost, so the "top" feature is chosen by volume. The Overview's
own category table *does* carry a cost per category, so the data to rank by money is already there.

## Fix

**Fixed 2026-10-21 by the TASK-147 redesign** (overview → provider/feature → call): the *Top feature* tile is gone. *By feature* and every *Used by* list switch between Calls and Cost, and a group's facts name the top user by calls and, separately, by cost ("Browser agent 80 % of cost").

Not implemented in this task (TASK-147 is a content review). The proposed direction is in
`docs/tasks/TASK-147/SUGGESTIONS.md` §4: rank by cost, or show both — **most used** and **most
expensive** — and rename the tile to **Feature** (the category) so it stops colliding with the
Usage and Calls tabs' **Feature** column (the usage key).

## Verification

1. On the Overview, the tile must name the category with the highest cost for the selected period
   (with the Usage tab's cost column as the cross-check).
2. If it keeps ranking by volume, it must say so — "Most used feature" — and a second tile must
   carry the cost ranking.
3. The tile's name and the Usage tab's column header must not refer to different things.

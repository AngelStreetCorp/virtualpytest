# BUG-0736 — The AI usage Usage tab renders an 820 px table on a 390 px phone: not one number is visible

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0736                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                        |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | `d5289bf` (deployed 2026-10-21, build 89471)                |

---

## Symptom

On a phone (390 px wide), `/monitoring/ai-usage` shows a reduced tab strip — **Overview / Errors /
Calls** — but the Usage tab is still reachable: the Overview's "Explore" cards and the "‹ Usage"
breadcrumb link open it.

What the user gets is the **desktop** table at phone width. Only three columns fit:

| Fits | Cut off |
|---|---|
| Category | **Requests** |
| Source | **Errors** |
| Model (itself truncated) | **Tokens**, **Cost**, **Last** |

There is no horizontal scrollbar and no mobile variant of the Usage table, so **the user sees no
request count, no error count, no token count, no cost and no timestamp** — the table shows
feature names and nothing quantitative. It is the page's most decision-relevant tab, and on a
phone it answers nothing.

The same tab strip also leaves **no tab marked active** on Usage, Efficiency, Providers or Training,
because the mobile strip only knows about Overview / Errors / Calls.

## Root cause

The page branches on `isMobile` (`frontend/src/hooks/useResponsiveMode.ts:10-12`, mobile ≤ 767 px)
and provides mobile components for three tabs only:

```
frontend/src/components/aiUsage/MobileAiUsage.tsx
frontend/src/components/aiUsage/MobileOverview.tsx
frontend/src/components/aiUsage/MobileCalls.tsx
frontend/src/components/aiUsage/MobileErrors.tsx
```

`UsageTab.tsx` has no mobile counterpart, so the desktop component renders unchanged. Its table
has a fixed minimum width:

```tsx
<Table sx={{ minWidth: 960 }} ...>   // the Usage table's fixed layout
// frontend/src/components/aiUsage/UsageTab.tsx
```

which cannot fit 390 px. The page's own breakpoint is `max-width: 767px`, and the **tablet**
range (768–1199 px) has no layout at all — it gets the desktop page in a narrower box, where the
same table is cut off and the top navigation bar overlaps itself (visible in the captured
900 px screenshot: "Interface" is drawn on top of "Monitoring").

## Fix

**Fixed 2026-10-21 by the TASK-147 redesign** (overview → provider/feature → call): the 820 px table and the phone shell are gone. One layout for every width: tiles 2 × 2, lists one column, the call table keeps Time · Feature · Cost · Result. Checked at 375 px with no sideways scroll.

Not implemented in this task (TASK-147 is a content review). The proposed direction is in
`docs/tasks/TASK-147/SUGGESTIONS.md` §4:

1. **Give the Usage tab a mobile layout** — as cards, like `MobileCalls` and `MobileErrors` — or
   hide it on phones and link to it from the Overview;
2. **mark the active tab** on the mobile strip for the four tabs it does not show;
3. **add a tablet layout** for 768–1199 px, or move the breakpoint so the desktop table is never
   shown below its minimum width.

## Verification

1. At 390 px, open the Usage tab (from the Explore cards and from the breadcrumb): every column
   must be readable, or the tab must not be offered.
2. At 390 px, on each tab, the active tab must be visibly marked.
3. At 900 px, the top navigation bar must not overlap, and the Usage table's **Cost** column must
   be reachable.
4. Compare against the captured screenshots in `docs/tasks/TASK-147/screens/`:
   `usage-mobile-dark.png`, `usage-tablet-dark.png`.

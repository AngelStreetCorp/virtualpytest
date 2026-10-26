# BUG-0784 — The dashboard's "AI usage" tile prints a money amount with three decimals, and in German reads $22,039

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0784                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | —                                                             |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-08, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** / (Dashboard > System tab)
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open the Dashboard, tab System.
2. Read the "AI usage" card in the bottom row.
3. Switch the language to German and read it again.

**Expected:** A readable spend such as $22.04 (and 22,04 in German).

**Actual:** The card reads `$22.039` (API value 22.039). In German it becomes `$22,039`, which a German reader parses as twenty-two thousand, a 1000x error on the number that reports platform spend. The tile formats by hand (`frontend/src/components/dashboard/cards/systemCards.tsx:176`, `formatNumber` with no options, `i18n/index.ts:163`); the AI usage page already has the right `fmtCost` (`components/aiUsage/format.ts:41`).

Evidence:

- [ops-08-ai-usage-currency.png](../tasks/qa-evidence/ops/ops-08-ai-usage-currency.png)

## Root cause

`frontend/src/components/dashboard/cards/systemCards.tsx:176` formatted the amount itself:

```tsx
value={`$${formatNumber(ai.cost_7d)}`}
```

`formatNumber` is `n.toLocaleString(locale, opts)` (`frontend/src/i18n/index.ts:163`) — with no options, `Intl.NumberFormat` prints **up to three fraction digits**, so 22.039 came out as `22.039` (English) and `22,039` (German). In German the comma is the decimal separator, so `$22,039` reads as twenty-two thousand: a 1000x error on the number that reports the platform's spend.

The app already had the right formatter — `fmtCost` (`frontend/src/components/aiUsage/format.ts:41`), used everywhere on the Monitoring > AI usage page: two decimals, sub-cent amounts keep their significant digits instead of rounding to $0.00, and the locale's own separators. The dashboard card simply did not use it.

The same hand-formatting appeared on one more line of the same feature: the monthly AI budget line on Settings > AI (`frontend/src/components/settings/ai/PricesTab.tsx:217-218`) printed `$${b.spent}` and `$${b.forecast}` — the raw floats, three decimals and all. Fixed in the same pass.

## Fix

- `frontend/src/components/dashboard/cards/systemCards.tsx` — the "AI usage" card now uses `fmtCost(ai.cost_7d)`, the formatter the AI usage page already uses.
- `frontend/src/components/settings/ai/PricesTab.tsx` — the budget line (limit, spent, forecast) uses `fmtCost` too.

Nothing else changed: the API value is the same, only its rendering.

## Verification

Real browser, the dashboard's System tab (`scripts/agent/dashboard_ai_usage.py`, reading the card's own value):

| | before (live) | after (worktree) |
|---|---|---|
| the card (English) | `$20.188` | **`$20.19`** |
| the card (German) | `$20,188` | **`$20,19`** |

(The QA sweep caught the same card at `$22.039` — the spend moves, the three decimals do not.) After the deploy (build main-2026.10.22-89636) the live card reads **`$20.11`**, two decimals.

Re-checked after the deploys that followed: the live card reads **`$20.18`** — still two decimals (`scripts/agent/dashboard_ai_usage.py`). The spend moves; the decimals do not.

Screenshots: [before (live)](../../tasks/qa-evidence/fix/bug-0784-before-live.png) · [after (worktree)](../../tasks/qa-evidence/fix/bug-0784-after-worktree.png) · [after, German](../../tasks/qa-evidence/fix/bug-0784-after-worktree-de.png) · [after (live, deployed)](../../tasks/qa-evidence/fix/bug-0784-after-live.png).

Tests: `tests/frontend/DashboardAiUsageCard.test.tsx` — 8 cases: the tile prints `$22.04` for 22.039, `$0.46` for 0.4567 and `$1,200` for 1200; in German it prints `$22,04` and **not** `$22,039`; plus the formatter's own rules (two decimals, a sub-cent amount keeps its digits, a missing value prints nothing). Against the pre-fix sources the two English cases and the German case fail.

Checks: `tsc --noEmit` 0 errors · eslint clean on the changed files · the dashboard card suite 8/8 passing.

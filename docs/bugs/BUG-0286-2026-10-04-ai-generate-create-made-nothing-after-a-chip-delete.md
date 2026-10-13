# BUG-0286 — AI Generate on a phone created nothing once a proposal chip was deleted

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0286                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — on Android and web, removing one wrong proposal made Create do nothing |
| Area      | `frontend/src/components/navigation/AIGenerationModal.tsx` (`deleteItem`), `frontend/src/hooks/useGenerateModel.ts` (`continueExploration`) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

In the navigation editor on a phone (Google TV), AI Generate proposed search, 4_tvs_nearby, shop,
library and watchlist. After deleting the `4_tvs_nearby` chip and clicking *Create Nodes/Edges*,
the modal closed and the interface still had only `home` and its entry edge. No validation
prompt appeared. The host logged *"All items from plan: []"*.

## Root cause

The chip's delete was written for TV plans, whose items sit in rows (`lines`): it rebuilt the
item list from the rows. A phone or web plan is click-based and has no rows, so one delete left
the plan with no items at all. Create then sent that empty row list as `cleaned_lines`, and the
host replaced the plan's items with it.

## Fix

- A chip of a click-based plan is deleted by value, and it also leaves the selection.
- Create sends `cleaned_lines` only when the plan has rows.

## Verification

- `tsc --noEmit` passes.
- The browser repro on a local build of this commit, against the S21x (2026-10-04): editor → AI
  Generate → Start (30 s) → delete `4_tvs_nearby` → Create Nodes/Edges created search, shop,
  library, watchlist → Start Validation 8/8 (~2 min) → Review Node Verifications → Save (4) →
  Confirm & Save. The host logged *"User selected 4/5 items"*.

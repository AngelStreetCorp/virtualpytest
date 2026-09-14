# BUG-0029 — Standby edge picker goes disabled when a variant re-wires the into-standby edge

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0029                                                     |
| Reported  | 2026-07-28                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (one script's edge picker, per-variant)                  |
| Area      | frontend / Run Tests — standby_measurement edge picker       |
| Fixed in  | build 8713                                                   |
| Commit    | `9a90800e6`                                                  |

---

## Symptom

On the Run Tests page, selecting a **variant** for a `standby_measurement` item left the
**edge** dropdown **disabled** (greyed out) instead of refreshing with the variant's edges.
The field still displayed a stale `live → standby` label, but could not be opened.

Reproduced on `example_tv` variant `base_5.28`, where the standby transition had been
re-wired to `home → standby` and the old `live → standby` edge disabled.

## Root cause

The standby edge picker filtered the KPI action-set list on the **whole label** containing
**both** `live` **and** `→ standby`:

```js
const STANDBY_EDGE_FILTER = ['live', '→ standby'];
```

`live` was an over-specification of the real intent ("the edge whose target node is
standby"). Once the variant re-wired the edge to `home → standby`, no label contained
`live`, so the filter matched **zero** edges → `actionSets.length === 0` → the
`EdgeKpiSelector` `FormControl` rendered `disabled`. The stale value persisted because the
selector deliberately does not clear the current value while the list is empty (avoids
wiping it during load).

The `/server/navigationTrees/kpi-action-sets` endpoint was returning the correct
variant-resolved edge (`home → standby`) all along — the drop was purely the client filter.

## Fix

Filter on the **destination node label** instead of substring-matching the whole label.
`KpiActionSet` already carries `to_label`, so the picker now keeps action-sets whose target
node label equals `standby`:

- `EdgeKpiSelector.tsx` — replaced the `labelIncludesAll?: string[]` substring filter with
  `toLabelEquals?: string` (exact, case-insensitive `to_label` match).
- `ScriptParameterRow.tsx` — the standby edge now passes `toLabelEquals="standby"`.

This surfaces **any** into-standby edge regardless of source (`live → standby`,
`home → standby`, …), which is the original intent. Matching `to_label` exactly (rather than
a `→ standby` substring) also stops `→ standby_active/eco/fast` edges — which belong to the
separate `standby_mode_node` picker — from being caught.

## Verification

- Variant `base_5.28` (re-wired `home → standby`): the picker now refetches on variant
  select, the reset effect clears the stale `live → standby` value, and the preselect effect
  auto-picks `home → standby` — enabled, not disabled.
- Base scope (`live → standby`): unchanged — still offered and preselected.
- No `→ standby_active/eco/fast` mode-node edges leak into the picker (exact `to_label`
  match, not substring).

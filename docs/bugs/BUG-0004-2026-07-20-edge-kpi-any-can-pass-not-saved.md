# BUG-0004 — Edge KPI "Any can pass" verification setting doesn't save

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0004                                                     |
| Reported  | 2026-07-20                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                           |
| Area      | frontend / navigation editor                                  |
| Fixed in  | build 8713                                                   |
| Commit    | `fd7bbca91`                                                  |

---

## Symptom

On an edge's KPI Measurement section (e.g. a `standby → live` edge), selecting **"Any can
pass"** for the KPI verifications and saving appeared to work, but reopening the same edge
always showed **"All must pass"** again — the choice never stuck.

## Root cause

`VerificationsList` (`frontend/src/components/verification/VerificationsList.tsx`) always
renders the "All must pass" / "Any can pass" `<Select>`, but only persists a selection when
the parent supplies `passCondition` + `onPassConditionChange`. When those props are omitted,
the component falls back to its own local `internalPassCondition` state, initialized to
`'all'` on every mount.

`Navigation_EdgeEditDialog.tsx`'s KPI `VerificationsList` (used for
`actionSet.kpi_references`) never passed either prop. So changing the dropdown only mutated
that throwaway local state — nothing wrote it into `edgeForm`, Save never persisted it, and
reopening the dialog remounted the component fresh at the `'all'` default.

The backend already has a place to read this from: `navigation_executor.py`'s
`_resolve_kpi_pass_condition` looks at `kpi_references[0]['verification_pass_condition']`
(falling back to the destination node's own `verification_pass_condition`, then `'all'`) —
but the frontend was never writing that field.

## Fix

`frontend/src/components/navigation/Navigation_EdgeEditDialog.tsx`: derive
`kpiPassCondition` from `actionSet.kpi_references[0].verification_pass_condition` and pass it
(+ an `onPassConditionChange` handler that stamps `verification_pass_condition` onto every
item in `kpi_references` via the existing `edgeEdit.handleKpiReferencesChange`) into the KPI
`VerificationsList`. This routes the selection through the normal edge save path instead of
the component's un-persisted internal fallback.

Note: if the KPI reference list is empty, there is nothing to stamp the value onto yet, so the
selection is a no-op until at least one KPI verification is added — mirrors the backend, which
also needs `kpi_references[0]` to exist to resolve anything but `'all'`.

## Verification

1. Open an edge with at least one KPI reference verification (e.g. `standby → live`).
2. Set the KPI pass condition to "Any can pass" and Save.
3. Reopen the same edge — the dropdown still shows "Any can pass".
4. `tsc --noEmit` clean on the changed file.

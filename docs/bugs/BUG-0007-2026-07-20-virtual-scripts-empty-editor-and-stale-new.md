# BUG-0007 — Virtual Scripts opens on an empty editor, and "New" keeps the old interface/variant

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0007                                                     |
| Reported  | 2026-07-20                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / Test → Virtual Script builder                     |
| Fixed in  | build 8713                                                   |
| Commit    | `6af64583e`                                                    |

---

## Symptom

Two defects on the **Virtual Script** page (`frontend/src/pages/VirtualScripts.tsx`):

1. **Opening the page shows an empty editor.** The Scripts rail lists the saved scripts, but
   nothing is loaded — Name, Description and the code pane are blank until you click a row.
2. **"New" does not fully clear the form.** After loading a script and clicking **+ New**, the
   Interface and Variant selectors in the header still hold the *previous* script's values.

## Root cause

1. Nothing ever called `handleSelect` on mount. `listScripts()` populated the rail; selection was
   click-only.
2. `handleNew` reset `selectedId`, `name`, `description`, `doc`, `source`, `params` and
   `paramValues` — but **not** `userinterfaceName` / `variant`. Those two are only ever written by
   `seedParamDefaults`, which seeds conditionally (`setUserinterfaceName(prev => prev || …)`) so it
   deliberately never overwrites a non-empty value. With nothing clearing them, a stale
   interface/variant survived New indefinitely and was silently used to build the run args.
   `confirmDelete` had the same gap.

## Fix

- Added a ref-guarded effect that calls `handleSelect(scripts[0].id)` once the list first arrives.
  The `autoSelectedRef` guard matters: `listScripts()` is re-run after Save and Delete, and without
  it that refresh would yank the user off whatever they were editing back to the first script.
- `handleNew` now also clears `userinterfaceName`, `variant` and `versions`, and sets
  `autoSelectedRef.current = true` so a first-load race cannot overwrite the fresh template.
- `confirmDelete` clears `paramValues`, `userinterfaceName` and `variant` for the same reason.

## Verification

- `npx tsc --noEmit` — no errors reported for `VirtualScripts.tsx`.

Not verified: the page was not exercised in a running browser this session. Confirm on the deployed
build that (a) the first script loads on page open, and (b) after New the Interface/Variant
selectors are empty.

## Notes / left alone

- The params strip repopulating (`node = home`) after **New** is **not** part of this bug — those
  values come from the starter template's own `_script_args` defaults, re-seeded by the debounced
  analyze pass. That is correct behaviour; changing it means changing `STARTER_TEMPLATE`.

# BUG-0023 — Editing a conditional sibling's KPI name/threshold unlinks the edge

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0023                                                     |
| Reported  | 2026-07-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / navigation                                       |
| Fixed in  | build 8713                                                   |
| Commit    | `5cf930321`                                                 |

---

## Symptom

Opening the Edit dialog on a **conditional sibling** edge showed the **main** edge's KPI name,
threshold and final-wait values instead of the sibling's own. Editing any of those fields and
saving **silently unlinked** the sibling from its conditional group, even though the author only
changed a per-branch KPI field.

## Root cause

KPI name / threshold / final-wait are **per-branch** (each conditional sibling has its own), but the
dialog read and wrote the **main** edge's values, so it displayed the wrong data and stamped it back
onto the sibling. And the save path unlinked the edge on **every** save, regardless of whether the
change actually touched the fields (the action lists) that define the conditional link.

## Fix

`5cf930321`:

- The Edit dialog now shows and saves the **sibling's own** KPI name / threshold / final-wait.
- Saving only **unlinks** the edge when the **action lists** were actually changed; editing just a
  KPI field leaves the conditional link intact. The unlink confirmation dialog now appears **only**
  in the action-list-changed case.

## Verification

1. Edit a conditional sibling's KPI name or threshold only, Save → it persists, the edge stays
   linked, and no unlink confirmation appears.
2. Change the sibling's action list → the unlink confirmation appears as before.
3. Reopen the sibling → it shows its own KPI values, not the main's.

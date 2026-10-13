# BUG-0232 — Test Builder: one change needed several Undo presses, and Undo itself broke the history

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0232                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed — deployed and verified 2026-10-02                     |
| Severity  | Medium — Undo looked broken (the first presses changed nothing visible), and Redo was unreliable |
| Area      | `frontend/src/contexts/testcase/TestCaseBuilderContext.tsx` (undo/redo history) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

In the Test Builder (host-clone-1, TASK-36), an AI edit's **Apply** added one block. Undo took
it away only on the **third** press: presses 1 and 2 changed nothing visible (Playwright, 2026-10-01).
Loading a testcase and AI generation behaved the same.

## Root cause

The history pushed an entry on **every** change of the `nodes` / `edges` arrays. ReactFlow
rewrites `nodes` when it measures blocks after they render, on selection, and on every mouse
move of a drag, so one real change left several near-identical entries. Undo and Redo set
`nodes` themselves, which pushed one more entry and cut off the redo branch.

## Fix

An entry is pushed only when the graph's content changes: block id, type, data and rounded
position, and the connections (`historyKey`). Size, selection and drag state are ignored, and a
drag is recorded once when it ends. Undo and Redo flag their own restore, which is not
recorded.

## Verification

- `tsc --noEmit` and ESLint pass.
- After the frontend deploy (Playwright, host-clone-1, 2026-10-02): Test Builder → AI → Edit open
  graph → Apply added `verification_2`. **One** Undo removed it, one Redo brought it back, and Undo
  removed it again (before: 3 presses, the first two with no visible change).

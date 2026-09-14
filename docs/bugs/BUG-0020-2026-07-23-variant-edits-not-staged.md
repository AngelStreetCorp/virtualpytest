# BUG-0020 — Variant edits write to the server immediately (no staged Save / Discard)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0020                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / navigation / variants                            |
| Fixed in  | build 8713                                                   |
| Commit    | `fe70ba488` (+ `98ee552b8`)                                  |

---

## Symptom

While a variant was selected, deleting / disabling / revealing edges or nodes wrote to the server
**immediately**: the yellow unsaved indicator never armed, **Discard** couldn't revert the change,
and the edits didn't participate in the single-Save model that base edits and node moves use. A
related symptom: because a variant edge's **row** and its **enable marker** were written in separate
operations, a partially-applied write could leave the edge invisible (an enabled marker pointing at
a row that hadn't landed, or vice-versa). Variant direction delete also flipped the surviving
direction's panel labels.

## Root cause

Variant edits bypassed the staging layer entirely and called the persistence path directly, one
mutation per operation. There was no in-memory staged diff for a variant, so nothing armed the
unsaved indicator and Discard had nothing to roll back. The two-write edge create/enable was the
source of the "invisible variant edge" skew.

## Fix

`fe70ba488` (+ `98ee552b8`):

- **Every variant edit now stages like base** — deletes, disables and reveals accumulate in the
  staged diff, arm the yellow **Save**, and flush in **one write per variant** on Save; **Discard**
  reverts them all.
- The edge **row and its enable marker land on the same Save**, so the skew that produced invisible
  variant edges is structurally gone.
- Variant direction delete clears the action set **in place** without inverting the surviving
  direction's labels.

## Verification

1. On a variant, delete/disable/reveal a few edges and nodes → Save turns yellow and nothing has
   hit the server yet; **Discard** reverts everything.
2. Click **Save** → one write per variant persists all changes together; a newly enabled variant
   edge is visible immediately (row + marker consistent).
3. Delete one direction of a bidirectional edge on a variant → the surviving direction keeps its
   correct labels.

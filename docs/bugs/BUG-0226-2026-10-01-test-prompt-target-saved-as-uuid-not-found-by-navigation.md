# BUG-0226 — Test Prompt: a target picked on the page was stored as a UUID that navigation cannot find

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0226                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed — deployed and verified 2026-10-01                     |
| Severity  | High — Explore of any prompt whose target was picked on the page fails at pre-navigation |
| Area      | `features/ai-test/frontend/components/TestPromptForm.tsx` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

With BUG-0225 fixed, the prompt *TASK-36 check: sauce-demo products* opened with Target Screen
`products`. Explore from the page then failed in 1.5 s: `Pre-navigation failed: Target node
9bb8163e-4221-419b-8b2b-814d9bcef2de not found in unified graph. Available nodes:
['entry-node', 'home', 'products', …]` (host-clone-1, 2026-10-01 16:04 UTC).

## Root cause

The Target Screen dropdown used each tree node's row UUID (`n.id`) as its value and saved it
as `target_screen_node_id`. Navigation resolves a target by its `node_id` (`products`). That
covers the unified graph and the server's pre-navigation, which also picks the root by
`node_id` first. So a target picked on the page could never be reached. One more saved
prompt in the DB (`5db4d7f1`, target `home`) still holds a UUID, and will show an empty Target
until it is picked again.

## Fix

The dropdown uses `node_id`, and falls back to the UUID only for a node without one.

## Verification

- `tsc --noEmit` passes.
- After a frontend deploy: Explore from the page on host-clone-1 pre-navigates to `products`
  and runs (TASK-36 task doc §2.7).

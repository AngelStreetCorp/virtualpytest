# BUG-0225 — Test Prompt: every saved prompt opened with its target screen wiped

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0225                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed — deployed and verified 2026-10-01                     |
| Severity  | High — Explore from the page pre-navigates to the tree's root instead of the target and fails; Save then stores the prompt without its target |
| Area      | `features/ai-test/frontend/hooks/useTestPromptPage.ts` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

On `/test-prompt`, the prompt *TASK-36 check: sauce-demo products* (target `products`) opened
with an empty **Target Screen**, although the dropdown lists `products`. Explore from the page
then failed in 1–2 s with `Pre-navigation failed: No unified path found to 'Entry'` (2026-10-01
13:12 and 15:59 UTC, host-clone-1). The same prompt passed Explore over the API, which sends
no form state.

## Root cause

An effect cleared `targetScreenNodeId` / `targetScreenLabel` whenever `userinterfaceName`
changed. Loading a prompt sets the form, target included, and then sets the interface to the
prompt's. That fired the effect, which wiped the target the load had just set. The page
then sent an empty target, and the server's pre-navigation fell back to the tree's root node
(`Entry` on `sauce-demo`), which has no path to itself.

## Fix

The effect is gone. The target is cleared only when the interface really changes away from
the prompt's: a manual pick in the Interface dropdown, or a device that cannot use the
interface (the fallback to its first compatible one).

## Verification

- `tsc --noEmit` passes.
- After a frontend deploy: the prompt opens with Target Screen `products`, and Explore from the
  page passes (TASK-36 task doc §2.7).

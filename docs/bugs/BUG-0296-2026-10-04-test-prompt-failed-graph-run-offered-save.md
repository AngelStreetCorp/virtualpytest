# BUG-0296 — Test Prompt: a failed graph run still offered Save as testcase

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0296                                                     |
| Reported  | 2026-10-04 (TASK-28 promo session, S21x phone on rpitest)    |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — a failing graph could be saved and then replayed as the prompt's test |
| Area      | `features/ai-test/frontend/components/TestPromptResults.tsx` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

A Run graph execution ended *Failed*, and its card still offered **Save as testcase**.

## Root cause

The button showed for any finished graph run that generated a graph (`isComplete` covers passed, failed and error).

## Fix

Save as testcase is offered only on a **passed** graph run, as it already was for explorations.

## Verification

- `tsc --noEmit` and `py_compile` pass.
- After the deploy: a failed graph run's card has no Save button.

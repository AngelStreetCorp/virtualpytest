# BUG-0295 — Test Prompt: a prompt name already in use made Run do nothing visible

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0295                                                     |
| Reported  | 2026-10-04 (TASK-28 promo session, S21x phone on rpitest)    |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the user saw no run and no clear reason |
| Area      | `features/ai-test/lib/test_prompts_db.py`, `useTestPromptPage.ts` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

Creating and running a prompt whose name was already used made Run silently do nothing.

## Root cause

`test_prompts` is `UNIQUE (team_id, name, version)`: the insert failed, the server returned the raw database error, and Run showed only a generic *Failed to save before execution* toast.

## Fix

A duplicate name (create or rename) returns *A prompt named 'X' already exists. Open it from the list, or choose another name.* (`duplicate_name: true`). Run and Save show the server's message.

## Verification

- `tsc --noEmit` and `py_compile` pass.
- After the deploy: Run with a used name shows that message.

# BUG-0294 — Test Prompt: the page declared runs over 3 minutes timed out while they went on

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0294                                                     |
| Reported  | 2026-10-04 (TASK-28 promo session, S21x phone on rpitest)    |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — any exploration over ~3 min showed as failed on screen, though it later passed |
| Area      | `features/ai-test/frontend/hooks/useTestPromptPage.ts` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

A 3-screen prompt on the S21x (Explore) showed *Execution timed out* on the page; the run continued on the server and passed. Run time varies with the go-home step.

## Root cause

The fallback poll stopped after 18 × 10 s (180 s) and marked the card *error* / *Execution timed out*. The server had declared nothing: an exploration is bounded by its skill's time limit (300 s of agent time, plus pre-navigation and the report).

## Fix

The page polls until the execution row has a final status and never declares a timeout itself. The poll stops after 2 h without touching the card. The socket's completion event still ends a run as before.

## Verification

- `tsc --noEmit` and `py_compile` pass.
- After the deploy: an Explore run longer than 3 min ends on the page with the server's status.

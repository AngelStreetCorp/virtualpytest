# BUG-0428 — AI comment dialog called automatic verdicts "Manual Review"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0428                                                     |
| Reported  | 2026-10-06                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend (AI Queue Monitor, Test Reports)                    |
| Fixed in  | build 90145 |
| Commit    | (this commit)                                                |

---

## Symptom

The "AI Analysis Comment" dialog (AI Queue Monitor → Scripts, and Test Reports) showed "Analysis Type: Manual Review"
on verdicts made automatically by Jev (`ai_auto_jev`) or by the analyzer's LLM (`ai_auto_openrouter`), and on
failed analyses (`ai_error`).

## Root cause

Both dialogs mapped only `ai` / `ai_agent` / `ai_and_human` (and, in the queue, `ai_strategy_skip`); every other
`check_type` fell through to "Manual Review". The automatic check types added since then were never mapped.

## Fix

One shared `analysisTypeLabel(check_type)` in `frontend/src/components/common/JevWhy.tsx`, used by both dialogs:
Jev (automatic), AI model (automatic), Skipped by sampling policy, AI analysis failed, AI Agent Analysis,
AI & Human Review, else Manual Review.

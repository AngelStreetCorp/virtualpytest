# BUG-0495 — AI usage training panel showed the text 'id' instead of data

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0495                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                          |
| Area      | backend / AI usage                                |
| Fixed in  | Unreleased                                                   |
| Commit    | `feat/ai-usage-review-r1`                                    |

---

## Symptom

Monitoring → AI usage → Training data showed the single word `'id'` where the panel should be.

## Root cause

`ai_training_samples_db.list_for_report()` selected no `id` column, but `_parse_row()` reads `row['id']`: every call raised `KeyError('id')` and the route returned its text.

## Fix

`shared/src/lib/database/ai_training_samples_db.py`: `list_for_report` selects `id`. Test through the DB function with a client that returns only the selected columns: `tests/shared/test_ai_training_samples_report_db.py`.

## Verification

Open the Training tab of Monitoring → AI usage: the table fills (or says there are no samples), no `'id'`.

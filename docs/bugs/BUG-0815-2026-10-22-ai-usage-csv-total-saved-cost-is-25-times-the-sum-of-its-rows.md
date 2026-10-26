# BUG-0815 — The AI usage CSV's TOTAL saved_cost is 25 times the sum of its rows

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0815                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Low                                                       |
| Area      | backend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-11, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /monitoring/ai-usage > Export CSV (`GET /server/ai-routing/usage/export`)
- **Viewport / theme:** n/a (export)

Steps to reproduce:

1. Export the AI usage CSV.
2. Add up the `saved_cost` column of the detail rows and compare with the TOTAL row.

**Expected:** TOTAL equals the sum of the rows.

**Actual:** Rows add up to $0.00614, TOTAL says $0.15718 for the same 807 avoided calls (the row prices them at its own average, the TOTAL at the global average). Every other column reconciles. The export is the one described as "charge back to a team, invoice a customer". Same formula family as BUG-0733 on another surface.

Evidence:

- None (API / export finding; see the finding text).

Related bugs: BUG-0733.

## Root cause

Not diagnosed yet: the QA sweep reported the symptom only.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

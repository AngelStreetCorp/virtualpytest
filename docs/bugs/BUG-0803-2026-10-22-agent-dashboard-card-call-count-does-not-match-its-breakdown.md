# BUG-0803 — An Agents dashboard card's headline "N calls" does not match the breakdown printed under it, and Atlas shows 0 errors above "1 err"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0803                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend / backend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-02, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /agent-dashboard (Overview)
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open `/agent-dashboard`.
2. Compare each card's headline with the sum of its rows (or `GET /server/agents/overview?hours=24`, `stats.calls` vs `parts[].calls`).

**Expected:** The headline equals the sum of the rows.

**Actual:** Atlas 283 vs 228, Sherlock 49 vs 369, Nightwatch 11 vs 0, Browser agent 86 vs no rows, "other" 2,140 (8 errors) vs no rows. Atlas says "0 errors" while its row says "Routing decisions 114 - 1 err".

Evidence:

- [agent-dashboard.png](../tasks/qa-evidence/analyst/pass1/agent-dashboard.png)

## Root cause

`frontend/src/components/agentDashboard/AgentCard.tsx:49` renders `stats.calls`/`stats.errors`; lines 62-72 render `parts` from a different query.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

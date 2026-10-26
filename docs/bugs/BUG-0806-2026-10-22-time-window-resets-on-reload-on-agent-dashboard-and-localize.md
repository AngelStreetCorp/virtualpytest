# BUG-0806 — The selected time window is silently lost on reload on the Agents dashboard and on Localize, while AI usage and Quality keep theirs in the URL

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0806                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding ANALYST-A-13, in `docs/tasks/QA-ANALYST-findings.md`); reproduced against the live app.

- **Page / route:** /agent-dashboard and /monitoring/localize
- **Viewport / theme:** 1440 px

Steps to reproduce:

1. Open `/monitoring/localize` and click 7d (the URL does not change).
2. Press F5.
3. Repeat on `/agent-dashboard` with 7 d.

**Expected:** The chosen window survives a reload and a shared link, as on `/monitoring/ai-usage` (`?period=720`) and `/test-results/quality` (`?window=`).

**Actual:** Both pages come back on 24 h, with different totals and no message.

Evidence:

- [pass2b-reports-campaigns.png](../tasks/qa-evidence/analyst/pass2b-reports-campaigns.png)

## Root cause

The window lives in plain React state on those two pages; AI usage uses `searchParams` (`MonitoringAiUsage.tsx:46`), Quality `?window=` (`QualityPageShell.tsx:28`).

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.

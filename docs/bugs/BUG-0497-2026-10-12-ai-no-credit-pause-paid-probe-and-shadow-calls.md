# BUG-0497 — The AI no-credit pause ended with a paid call that was sure to fail, and shadow calls kept probing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0497                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                          |
| Area      | backend / AI gateway                                |
| Fixed in  | build 90145 |
| Commit    | `feat/ai-usage-review-r1`                                    |

---

## Symptom

After BUG-0492 a paused provider was still probed by a real, paid request every 2, 4, 8 … minutes, and Jev shadow usages (localize second opinion, Sherlock verdict, freeze triage) were the ones sending it. The page showed no trace of the calls that were held back.

## Root cause

`router._note_credit` only knew a doubling timer: the first call after it was the probe, whichever usage made it.

## Fix

`shared/src/lib/ai/router.py`: when the wait is over a free credit check (OpenRouter `/api/v1/credits`) ends the pause or extends it with no request; if the balance cannot be read the wait grows 5 → 15 → 60 min and a normal usage is the probe. Shadow usages (`usages.SKIPPABLE_WHEN_PAUSED`) are never the probe: while their provider is paused they are skipped and recorded as `outcome = skipped`, `stop_reason = provider_paused` (counted, not listed). Tests: `tests/shared/test_ai_gateway.py`.

## Verification

Count skipped calls: `SELECT usage_key, count(*) FROM ai_calls WHERE outcome='skipped' AND stop_reason='provider_paused' GROUP BY 1`. While the account has no credit, failed `no_credit` calls stay at one per 5/15/60 min per process, or zero when the credit check can read the balance.

# BUG-0482 — Script triage kept calling an AI provider that was down, failing every result

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0482                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend (vpt-discard-scripts, Sherlock)                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

In 30 days, 634 script results ended `check_type = ai_error` with `HTTP 402` (provider out of credits): every
analysed result made a call that was certain to fail, both for the Jev decision step (`text.decision.sherlock`) and
for the LLM (`analyzer.sherlock`). Jev alone logged 413 failed calls.

## Root cause

`sherlock_jev.ask` and `SherlockHandler._classify_with_llm` called the provider for every result with no memory of
the previous failure. The alert worker already had a back-off (BUG-0299 follow-up, TASK-84); script triage did not.

## Fix

`backend_server/src/agent/core/backoff.py`: after a provider failure a step is not called for 1 h, after the next
failure 5 h, then 24 h for every later one; one success resets it (`ANALYZER_BACKOFF_S` overrides the steps).
Jev and the LLM each have their own: a paused Jev lets the LLM decide alone; a paused LLM falls back to Jev's gated
verdict, else writes `[AI_ERROR] analyzer.sherlock paused until HH:MM UTC ...` with no call. State is in memory, so a
worker restart probes once. Also routed `analyzer.sherlock` to MiniMax M2.7 highspeed (an `ai_routes` row).

## Verification

`python3 -m pytest tests/shared/test_sherlock_backoff.py tests/shared/test_sherlock_jev.py -q`. Live: the
`vpt-discard-scripts` journal shows `Jev paused 1 h` once, then no more Jev failures for an hour.

# Direct Queue Analyzer Test Strategy

## Goal
Validate the new direct analyzer loop (no chat loop) for `p2_scripts` with smart policy:
- Failures: first + every Xth repeated failure
- Successes: deterministic sample (default 10%)

## Required Env
- `ANALYZER_DIRECT_MODE=true`
- `OPENROUTER_API_KEY=...`
- Optional:
  - `ANALYZER_OPENROUTER_MODEL=google/gemini-2.0-flash-exp:free`
  - `ANALYZER_REPEAT_EVERY_FAIL=5`
  - `ANALYZER_SUCCESS_SAMPLE_PERCENT=10`
  - `ANALYZER_FAIL_LOOKBACK=20`

## Quick Functional Test
1. Run one script that creates a `script_results` row and queues `p2_scripts`.
2. Confirm `verification_review.md` URL exists in row metadata:
   - `metadata.verification_review_r2_url`
3. Wait for analyzer worker to consume queue.
4. Check row updated:
   - `checked=true`
   - `check_type` in `{ai_auto_openrouter, ai_strategy_skip, ai_error}`
   - `discard` and `discard_comment` present for analyzed rows

## Policy Test Matrix
1. Repeated Fail Suppression
- Trigger same failure 6 times for same script+device+error signature.
- Expect:
  - run #1 analyzed
  - runs #2-#4 skipped (`ai_strategy_skip`)
  - run #5 analyzed
  - run #6 skipped

2. Success Sampling
- Trigger 20 passing runs with varied result ids.
- Expect ~10% analyzed (deterministic by id hash), others skipped.

3. Markdown Fetch
- Ensure analyzer fetches `verification_review_r2_url`.
- Temporarily break URL on one row and verify `ai_error` path with error comment.

## Operational Strategy (Recommended)
- Analyze all first failures by signature.
- Analyze every 5th repeated same failure while issue persists.
- Sample 10% of passes.
- If discard rate spikes, temporarily raise pass sampling to 25%.
- Once fixed deployment lands, clear repeat suppression naturally by changed error signature.

## Monitoring
- Queue status: `/server/ai-queue/status`
- Script results: `/server/script-results/getAllScriptResults?team_id=<TEAM_ID>`
- Markdown debug endpoint:
  - `/server/script-results/getVerificationReviewMarkdown/<SCRIPT_RESULT_ID>?team_id=<TEAM_ID>`

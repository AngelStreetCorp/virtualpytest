# GOAL-03 — AI test lifecycle: testcases → campaigns → execution → analysis → report

**Status:** active
**Arbitrator:** the owner

Given a userinterface (GOAL-02's output), AI agents generate testcases, assemble them
into campaigns, execute, analyze results, and produce reports — with the arbitrator
approving what enters the test suite and reviewing the analysis verdicts that matter.

## End state (success criteria)

- From an approved "cover this userinterface" task, an agent produces testcases mapped
  to requirements with coverage accounting, assembles a campaign, and executes it.
- Every execution result is classified (Sherlock: VALID_PASS / VALID_FAIL / BUG /
  SCRIPT_ISSUE / SYSTEM_ISSUE) and a human-readable report is generated per campaign.
- The arbitrator only reviews: new testcases entering the suite, `BUG` verdicts, and
  low-confidence classifications — everything else flows unattended.

## Exists today / Gap

- **Exists:** testcase/campaign/requirement management skills; script execution +
  campaign runner; Sherlock batch classification via `vpt-discard-scripts` (Redis
  `p2_scripts`, ~300–500 tokens/analysis); report generation with validation
  conventions; AI test generation worktree (Phases 1–5 done for web).
- **Gap:** no closed loop from userinterface → generated testcase suite without
  per-step prompting; Android TV generation in progress; no confidence gate on
  Sherlock verdicts (every classification writes `discard` with equal authority).

## Guardrails

- **The `discard` decision is the blast radius**: a wrong SCRIPT_ISSUE/SYSTEM_ISSUE
  classification suppresses a real bug. Until a confidence gate exists, `BUG` and
  `VALID_FAIL` verdicts are never auto-discarded — they surface to the arbitrator.
- **Reports follow the established conventions**: inline base64 images in validation
  report .md (not signed URLs); click-through URLs use the production host base.
- **Generated testcases don't execute against production-locked devices** without an
  approved task naming the device window.
- **Coverage claims must be computed, not asserted** — a report saying "100% coverage"
  links the requirement↔testcase mapping that proves it.

## Arbitration gates (always require human approval)

- New testcases/campaigns entering the durable suite (first run can be a dry-run).
- Any verdict that would discard a `BUG` or `VALID_FAIL` result.
- Deleting or bulk-editing existing testcases.

## Active tasks

- (none yet — agent proposes; arbitrator approves)

## Log

- 2026-07-15 — Goal created.

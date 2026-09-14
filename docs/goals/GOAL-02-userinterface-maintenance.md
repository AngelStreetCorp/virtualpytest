# GOAL-02 — AI creates & maintains userinterfaces

**Status:** active
**Arbitrator:** the owner

AI agents create navigation trees (userinterfaces) for new apps/devices and keep
existing ones valid — nodes, edges, verifications, references — with the arbitrator
approving structural changes.

## End state (success criteria)

- For a new app/device, an agent can explore and produce a working userinterface
  (nodes + edges + verifications) that passes validation, from a single approved task.
- Existing userinterfaces stay green: when validation fails, an agent diagnoses
  (timing / wrong-key / verification classes) and fixes locators, references, and
  timeouts autonomously — structural (topology) changes only via approved tasks.
- Every maintenance cycle ends with a before/after validation diff as evidence.

## Exists today / Gap

- **Exists:** exploration skills (`explore-mobile`, `explore-stb`, `explore-web`);
  `ai_userinterfaces_*` knowledge tables with verified flows/quirks/fingerprints
  (docs/agent/navigation/AI_USERINTERFACE.md); validation fix loop — deterministic,
  proven 14→0 failing transitions (docs/agent/validation/VALIDATION_FIX_LOOP.md);
  failure-diagnosis ladder (docs/agent/validation/VALIDATION_ANALYSIS.md).
- **Gap:** no scheduled loop that runs validation → diagnose → fix → re-validate
  unattended; exploration still needs per-session prompting; android_tv fix loop needs
  image-reference tooling (no accessibility labels).

## Guardrails

- **Image verification threshold floor is 0.7** (default 0.8) — never lower a threshold
  below 0.7 to make a test pass; recapture the reference per-variant instead.
- **Different device models may need separate reference captures** even on the same
  UI/locale — don't share references across models to save work.
- **Reference edits require re-saving the node/edge** — inline snapshots don't update
  themselves.
- **Reference capture is two-step**: `/cropImage` then `/saveImage` + fuzzy area — never
  save uncropped full frames as references.
- **Topology changes (add/remove nodes or edges) are proposals**, not autonomous fixes —
  the fix loop's scope is locators, references, timeouts.
- Writes to production `userinterfaces` tables follow the app's normal routes; the
  `ai_userinterfaces_*` KB is where unverified exploration knowledge goes first.

## Arbitration gates (always require human approval)

- Creating a new userinterface for a new app/device (the initial tree lands via review).
- Any topology change to an existing tree.
- Deleting or superseding references in bulk.

## Arbitrator direction (2026-07-16) — creation first, distillation end-game

Focus on **userinterface creation** before maintenance. Strategic sequence:

1. **Frontier creates userinterfaces reliably** — the exploration skill stack must work
   end-to-end and its output must be *validatable* (a created UI proves itself via
   validation, not via trust).
2. **Every frontier-created UI is a training example** — exploration traces + resulting
   nodes/edges/verifications + validation outcome form a corpus.
3. **Only then train an open-source model** to replicate the creation process
   (frontier-as-teacher distillation — extends docs/tasks/LOCAL_LLM_FEASIBILITY.md
   beyond banner OCR to full UI exploration). Game-changer if it works: UI creation
   without frontier API dependency.

Known imperfections named by arbitrator: the creation process itself and the
fingerprint step are not yet reliable. Audit before building.

## Active tasks

- [TASK-02-audit-ui-creation-skill](../tasks/TASK-02-audit-ui-creation-skill.md) — **done** (findings + task ladder)
- [TASK-02-fix-skill-wiring](../tasks/TASK-02-fix-skill-wiring.md) — **done** (ladder 0+1: branch-sync + wiring)
- [TASK-02-consolidate-demo](../tasks/TASK-02-consolidate-demo.md) — **done** (feat/demo = consolidation line)
- Next up for arbitration: re-reviewed ladder on the consolidated branch

## Log

- 2026-07-16 — **Autonomy baseline experiment (arbitrator-directed): agent wins creation
  decisively.** Single-prompt frontier agent, raw MCP only, same box same day:
  13 nodes / 21 edges (13 live-validated, assumptions marked) / 6 verifications in
  16.2 min, ~94k tokens, zero human help — vs the harness's 3 nodes / 4 edges / 0
  validated with hand-authored DOM. Agent self-handled screensaver + swallowed presses
  (found the pattern: first OK/BACK after every transition is always swallowed) +
  carousel false-motion, and independently converged on nav-underline as the focus
  signal. Trajectory committed as corpus exemplar #2. ARCHITECTURE IMPLICATION for
  arbitration: agent explores → harness validates/fingerprints/pushes; the harness's
  explore machinery (DOM authoring, structure creator) is the part agents replace;
  distillation corpus = agent trajectories.

- 2026-07-16 — Ladder A-G COMPLETE + first live test on stb4/vpt-pi1 (rpitest). Live
  results: init+explore built 3 nodes/4 edges/9 probes on the customer home menu with
  DOM-cache sibling reuse; validate (oracle) correctly REFUSED the graph — root causes
  found: (1) old stb_tv tree's home_red.jpg is focus-dependent (ENTRY→home fails 0.000
  when home keeps last focus), (2) stb4 BLE presses drop/land late even at 2s waits.
  ARBITRATOR RULING implemented: builds are fully self-contained — all references to
  existing userinterfaces removed from the builder (init precondition = device on home;
  fingerprint self-anchoring; goto_home deleted). Corpus v0 committed
  (fixtures/traces/stb4_ladder_test_2026-07-16). Open follow-ups: BLE press-verify-retry
  during explore; focus-sibling verifications (unique-text yields [] for same-screen
  focus nodes); auto-DOM needs a non-OpenAI vision fallback (only OpenRouter key has a
  value); stb_tv home_red reference fix (feeds the maintenance loop).

- 2026-07-16 — Consolidation: main + feat/ai-test-generation merged into feat/demo
  (arbitrator: demo is the integration line). feat/demo now carries auto_builder +
  localize v6 + SKILL packs + test_prompts + wiring fixes. GOAL-02 work continues in
  the virtualpytest-demo worktree; ladder to be re-reviewed against auto_builder.

- 2026-07-16 — Ladder 0+1 done on feat/ai-test-generation: main merged in (5f92d9c8a),
  wiring fixes pushed (03e79d5d7) — hidden tools removed from skills, host cache
  propagation implemented, create_subtree unpack fixed, failed_items emitted.
  Arbitrator decides next step individually.
- 2026-07-16 — Audit complete (in docs/tasks/TASK-02-audit-ui-creation-skill.md):
  all findings hold on the branch; 7-item task ladder proposed.
- 2026-07-16 — Direction set: creation-first, distillation end-game. Audit of the
  UI-creation skill stack approved and started.
- 2026-07-15 — Goal created.

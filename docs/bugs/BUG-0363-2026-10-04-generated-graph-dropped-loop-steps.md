# BUG-0363 — A generated test passed after the AI's repeated steps were silently dropped

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0363                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (deployed to hosts 2026-10-04)                         |
| Severity  | High                                                         |
| Area      | backend_host / AI graph generation                           |
| Fixed in  | Unreleased                                                   |
| Commit    | `fdf5d952a`                                                  |

---

## Symptom

Test Prompt, Run graph, on a set-top box (`stb_tv`): "Go to live TV, zap 3 times and check the
picture moves after each zap" **passed** in 33 s, and so did its replay. The stream showed no zap:
the saved testcase was only `home → live`. The 3 zaps and the motion checks were never in it, so
the test passed on whatever the box showed.

## Root cause

Three things in `backend_host/src/services/ai/`:

1. The prompt preprocessor saw "3 times" and told the model "Create LOOP block with 3 iterations"
   (`ai_intent_parser.build_structure_hints_for_ai`). The step list the builder reads has no loop
   step, so the model answered:
   ```
   1. Navigate to: live
   2. LOOP 3 times:
    a. Navigate to: live_chup
    b. Verify: DetectMotion(duration=3)
   ```
2. The parser in `ai_builder._parse_ai_response` read only lines starting with a number and
   **skipped any line it could not read**. It kept step 1 and dropped the rest without an error.
3. A command the device does not have (`DetectMotion`; the real one is `waitForVideoToAppear`)
   would have become a block anyway.

The graph was then cached, so the same prompt got the same 1-step graph again.

## Fix

- `ai_step_list.parse_step_list` reads the STEPS section. A `LOOP|Repeat N times:` header with
  lettered or indented steps under it is written out N times. A numbered or lettered line that is
  not a step **fails the generation** ("Not a step: …"), and the run shows that error.
- `ai_builder._check_commands`: an action or verification command missing from the device's
  catalog fails the generation.
- The loop hint now says to write repeated steps out, one line each. The conditional hint now
  describes `[on fail: continue]` (the step list has no branches either).
- Graph cache `graph_format` 3 → 4, so graphs cached before the fix are never served again.

## Verification

- Parser on the model's answer above: `live`, then `live_chup` + check three times, then the next
  step. Prose between steps is still ignored; an unreadable numbered line and an empty repeat both
  raise.
- On the device (stb3, after the host deploy): the same prompt run with `regenerate: true` got
  `live`, then `press_key(CHANNEL_UP)` + `DetectMotion` three times. It **failed** at the first
  motion check instead of passing; the stream showed a still picture on that channel.
- A testcase saved before the fix keeps its short graph: re-run its prompt with `regenerate`.

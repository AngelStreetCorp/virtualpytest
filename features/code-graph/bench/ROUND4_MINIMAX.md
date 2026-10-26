# Round 4: `code_refs` measured with MiniMax (pre-registered 2026-10-19)

Written and committed **before any question exists**. Rounds 1–3 used Claude Sonnet/Haiku (`docs/agent/Graphify.md` §6).
MiniMax (M3 via `mcode exec`), the cheap coding agent the owner uses most, was never measured. This is a **measurement,
not a ship gate**: the tool is already shipped.

## Design
- **Questions:** 5 new, held-out, written by a fresh agent with no access to the tool, `Graphify.md` or
  `features/code-graph/`. Same 5 shapes as round 3: 2 × callers of a method with a common name where the receiver
  decides, 1 × route ↔ URL, 1 × module-function callers, 1 × two-levels-up impact. No target from rounds 1–3
  (`call_host`, `execute_navigation`, `identify_screen`, `RunStore.start`, `LeagueRunner.start`, `/script/analyze`,
  `clear_unified_cache`, `get_device_segment_duration`, `NavigationExecutor.execute_navigation`).
- **References:** per question one fresh tool-free agent (grep + reading), cross-checked by a separate AST pass;
  disagreements resolved by reading the lines; notes in `bench/reference_round4.json`. The tool is not consulted.
- **Tree:** one detached worktree at `origin/main` at freeze time (a parallel session changes `code_index`; we do not
  wait). CLI cache warmed there. Both arms run on it.
- **Arms:** A = docs + grep (forbidden to open `Graphify.md` / `features/code-graph/`). B = A + the `AGENTS.md`
  "Who calls what: `code_refs`" section and the tool description (`code_refs_tools.py` docstring), verbatim, **CLI only**
  (`python3 features/code-graph/scripts/gen_code_index.py --query X [--depth 2]`, no MCP). Prompt templates identical to
  round 3; both end with a ```json {"files": [...]} block.
- **Runs:** 5 per question per arm = **50 MiniMax runs** (`mcode exec`, MiniMax-M3, on codebox, ≤ 10 at a time).
  Questions are never re-run to make them pass.
- **Metrics:** F1 of the file set vs reference, KB of tool results read (from transcripts), tool calls, wall time,
  and whether arm B ran the CLI. Medians and means, per question and pooled.

## Pre-stated regression rule
If pooled MiniMax **arm B F1 is lower than arm A by ≥ 0.1**, **or** pooled **median KB read of B exceeds that of A**,
the result is recorded as a **regression** and the concrete fix (tool description or output change) is written in
this file. The tool code is not changed by this task.

## Results

Run 2026-10-19 on codebox, `mcode exec` (MiniMax-M3, thinking), frozen tree `b2939e7f6` (detached worktree of
`origin/main`), 8 at a time, 50 runs, all finished `succeeded`. Questions: `questions_round4.json` (fresh Sonnet agent,
no tool/doc access). References: `reference_round4.json` (one tool-free Sonnet agent per question + AST pass
`xcheck_round4.py`; notes inside). Scorer: `score_round4.py`. Raw: `results_round4_minimax.json`.
KB = KB of tool results read, median (mean). One arm-B run (R5 #2) gave the right six files but omitted the closing
code fence, so it has no parsable block; as in round 3 it is left out of the stats (strict scoring, counting it as 0:
B F1 0.870 instead of 0.906).

| Q | A F1 | B F1 | A KB | B KB | A calls | B calls | A s | B s | B ran CLI | n A/B |
|---|---|---|---|---|---|---|---|---|---|---|
| R1 `ADBUtils.click_element` | 1.000 | 1.000 | 49.7 (66.8) | 1.5 (4.3) | 16.4 | 2.8 | 40.3 | 13.8 | 5/5 | 5/5 |
| R2 `TelloRemoteController.execute_command` | 0.987 | 0.833 | 131.7 (126.7) | 1.5 (1.5) | 27.2 | 1.0 | 64.6 | 10.2 | 5/5 | 5/5 |
| R3 route `/server/script/status/<task_id>` | 0.750 | 0.715 | 44.5 (45.9) | 8.8 (9.9) | 19.8 | 11.0 | 73.4 | 37.6 | 5/5 | 5/5 |
| R4 `normalize_script_ref` callers | 1.000 | 1.000 | 26.5 (24.4) | 1.5 (1.5) | 9.6 | 1.0 | 32.1 | 10.5 | 5/5 | 5/5 |
| R5 `resolve_script_identity` level 2 | 0.942 | 1.000 | 59.0 (63.5) | 1.7 (2.4) | 19.0 | 2.2 | 104.4 | 25.8 | 5/4 | 5/4 |
| **all** | **0.936** | **0.906** | **49.7 (65.5)** | **1.5 (4.0)** | **18.4** | **3.7** | **63.4 (76.5)** | **13.2 (20.1)** | **24/24** | 25/24 |

**Verdict against the pre-registered rule: no regression.** Pooled B F1 is 0.030 below A (0.066 under strict scoring),
under the 0.1 line, and median KB read is 1.5 vs 49.7 (3%, −97%; mean −94%). Median wall time 13 s vs 63 s, median calls
1 vs 20. MiniMax ran the CLI in 25/25 arm-B runs, usually once, and answered from it without a grep (R2, R4: exactly one
call). F1 is not better than grep, though: B is lower on two questions, and the cause is the tool, not the agent.

What MiniMax did and where B lost points:
- **R2 (B 0.833 in all 5 runs):** the CLI answered `TelloRemoteController.execute_command` with 5 files and said it had
  dropped 168 calls "with other receivers"; MiniMax trusted it and stopped. It missed
  `backend_host/src/routes/host_drone_routes.py` (`controller = get_remote_controller_by_type(device_id, "tello")`,
  a factory keyed by a string, so the receiver is untyped) and `tests/drone/test_tello_gevent_hub.py`. Arm A found them
  by grep (0.987) at 27 calls and 132 KB. The tool states "complete", so the agent never grepped.
- **R3 (both arms ≈ 0.72–0.75):** both over-included four `scripts/promo/*.js` files that hit the URL but are neither
  `frontend/` TypeScript nor Python (the question's scope), and B once added the assertion-only test. Not a tool
  fault; the tool indexes those `.js` literals and lists them. The tool did cost B calls here: querying the URL
  as written, `/server/script/status/`, printed the route but `url refs: 0`, while `/server/script/status/<task_id>`
  prints 11 refs. MiniMax then grepped (11 calls, 8.8 KB, 37.6 s): still less than A on KB (44.5) and time (73 s).
- **R5 (B 1.000 on 4 parsable runs):** B wins on accuracy here (A included the wrong-class `TestCaseTools.execute_testcase`
  callers in some runs). One B run omitted the closing fence (format slip, MiniMax only).
- R1 and R4: both arms perfect; B reads 3–6% of A's KB.

## Fixes to carry back (not done here; the tool code is not changed by this task)
1. **Do not claim completeness when calls were dropped on an untyped receiver.** After `dropped N calls ... with other
   receivers`, list the files among them that mention the class name or import its module (here `host_drone_routes.py`
   mentions `TelloRemoteController` and calls `get_remote_controller_by_type(..., "tello")`) under "possible callers
   (receiver type unknown)", and soften the tool description's "complete answer / do not grep" for `Class.method`
   queries to "complete for typed receivers; check the listed unresolved files".
2. **URL queries tolerate the concrete form.** `/server/script/status/` (trailing slash, or a concrete id such as
   `/server/script/status/abc`) should match the route `/server/script/status/<task_id>` and return its url refs;
   when a route matched with 0 refs, print "did you mean `<route>`".
3. A one-line scope note in the description: URL refs include `.js` literals outside `frontend/`; filter by the
   question's scope.

# validation

Validates all transitions in a navigation tree by testing each edge.

## Usage

```bash
python test_scripts/validation.py --userinterface example_mobile
python test_scripts/validation.py --max-iteration 10
python test_scripts/validation.py --edges "node1-node2,node2-node3"
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_mobile` | UI interface name |
| `--variant` | string | (empty = base) | Named variant override |
| `--max-iteration` | int | `0` | Max transitions to test (0 = all) |
| `--edges` | string | - | Comma-separated step numbers to validate (matches preview ordering) |
| `--subtree-root` | string | - | `node_id` of subtree entry; validates only that linked child tree |

## Workflow

1. Loads the optimal edge validation sequence from `find_optimal_edge_validation_sequence`.
2. For each step:
   - **Phase 1 — reposition.** If the device's tracked position differs from the step's `from_node`, navigate there via real pathfinding (`is_recovery=True` collapses the multi-hop reposition into one report row).
   - **Phase 2 — execute.** Run the precomputed single-edge step (action + verify).
3. On step failure, `NavigationExecutor` clears the tracked position; the next iteration's Phase 1 will reposition naturally.
4. Reports success rate and coverage percentage.

## Report rendering

| Step type | Badge | Row colour | Notes |
|---|---|---|---|
| Successful step | `PASS` (green) | green left border | actions + verifications expanded on click |
| Failed step | `FAIL` (red) | red left border | `❌ Error Details` block with verify report link |
| Skipped step (`skipped: True`) | `SKIP` (orange) | orange left border | `⏭️ Skip Reason` block (orange palette, *not* red) |
| Recovery row (`step_category: 'recovery'`) | `PASS` / `FAIL` (blue pill) | blue left border | Single collapsed row for the entire reposition; intermediate hops are suppressed by design. The row carries `step_start_screenshot_path` (captured before pathfinding) and `step_end_screenshot_path` (captured when the recovery resolves), so the click-through modal shows where the device started and where it landed without exposing the per-hop noise. |

## Failure dedup model

Two complementary skip mechanisms keep the run from wasting cycles on already-broken transitions:

### `unreachable_nodes` (node-level)

Populated when:
- A pre-step reposition fails → adds the immediate `from_node_id` (the reposition's target).
- A step execution fails → adds the `to_node_id` (we never landed there, so traversals starting from it can't run).

Checked at the top of every iteration: if `from_node_id` is in the set, the step is skipped with reason `'<from>' is unreachable from this run`. This is what produces the cluster of `⏭️` entries that follow an upstream `❌`.

> Population is conservative on purpose: only the immediate `from_node` of a failed reposition is added, never intermediate hops. In DFS traversal the same node appears as both `from` and `to` many times, and one failed reposition to a single-attempt target says nothing about reachability via *other* paths.

### `failed_attempts` (edge-attempt-level)

Keyed by `(from_node_id, to_node_id, action_set_id)`. Populated only on step execution failure (after the verify, not the reposition).

Checked at the top of every iteration: if the same triple is already in the set, the step is skipped with reason `edge attempt <from> → <to> already failed this run`.

**Why this matters.** The optimal-walk planner emits the same edge multiple times when it has to re-traverse it to reach different children. Without this dedup, a single broken edge produces *N* identical re-attempts — each preceded by a full `ENTRY → … → from_node` reposition — that can only fail the same way. Worked example from `docs/agent/validation_example_tv/validation_example_tv_2026-05-07.md`: Disney profile and Skyshow profile each appeared three times in the planned sequence and burned three identical attempts apiece.

**Why action-set granularity.** Edges can carry multiple `action_sets` (e.g. "press OK" vs "long-press OK", priority-ordered). One set failing doesn't condemn the others, so the dedup key includes `action_set_id`; the planner's step dict already exposes that field.

### Interaction between the two sets

| Scenario | `unreachable_nodes` skip? | `failed_attempts` skip? |
|---|---|---|
| Later step starts *from* a destination we never reached | ✓ | — |
| Later step re-attempts the *same edge* with the *same* action_set | — | ✓ |
| Later step re-attempts the same edge with a *different* action_set | — | ✗ (allowed to retry) |
| Later step targets the same destination via a *different* `from_node` | — | ✗ (allowed to retry) |

Only step *execution* failures populate `failed_attempts`. Reposition failures populate `unreachable_nodes` only — a failed reposition is about pathfinding/state, not about the edge under test.

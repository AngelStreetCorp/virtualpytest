#!/usr/bin/env python3
"""
Validation Script for VirtualPyTest

This script validates all transitions in a navigation tree using navigate_to().

Usage:
    python scripts/validation.py <userinterface> [--max-iteration <number>]
    
Example:
    python scripts/validation.py example_mobile
    python scripts/validation.py example_mobile --max-iteration 10
"""

import sys
import os
import time

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_args, get_context


# Declared at module top so the server's script-parameter analyzer (which reads
# only the first 300 lines of the file) always picks them up. They're attached
# to `main` near the bottom of the file.
_script_args = [
    '--userinterface:str:example_mobile',  # Framework param with default
    '--variant:str:',                              # Optional named variant; empty = base
    '--max-iteration:int:0',                       # Script-specific param
    '--edges:str:',                                # Script-specific param
    '--subtree-root:str:'                          # Script-specific param
]
_script_description = "Validate all navigation tree transitions."
_arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': "Optional variant name; if omitted, base data is used.",
    'max-iteration': 'Max transitions to test (0=all)',
    'edges': 'Comma-separated step numbers to test (matches the preview ordering)',
    'subtree-root': 'node_id of subtree entry — validate only that linked child tree',
}


def _get_validation_plan(context, subtree_root_node_id: str = None):
    """Get list of transitions to validate - optimized to use cache"""
    from backend_host.src.services.navigation.navigation_pathfinding import find_optimal_edge_validation_sequence
    from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name
    from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface

    # Active named variant for this run. The script executor sets it on the
    # device's navigation_context (always, not only for DB-tracked runs); fall
    # back to args for safety. None / '' = base scope. The plan MUST be built
    # from the variant-scoped graph or a chosen variant is silently ignored.
    device = context.selected_device
    variant = None
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if not variant:
        variant = getattr(context.args, 'variant', None)
    if isinstance(variant, str):
        variant = variant.strip() or None
    print(f"🎭 [_get_validation_plan] Variant scope: {variant or 'base'}")

    # Ensure we have tree_id
    if not context.tree_id:
        device = context.selected_device
        args = context.args

        # OPTIMIZATION: Get tree_id without loading full tree (lightweight DB query)
        userinterface = get_userinterface_by_name(args.userinterface, context.team_id,
                                                  mode=getattr(args, 'ui_mode', 'dev'))
        if not userinterface:
            print(f"❌ [_get_validation_plan] User interface '{args.userinterface}' not found")
            return []

        root_tree = get_root_tree_for_interface(userinterface['id'], context.team_id)
        if not root_tree:
            print(f"❌ [_get_validation_plan] No root tree found for interface '{args.userinterface}'")
            return []

        context.tree_id = root_tree['id']
        print(f"✅ [_get_validation_plan] Found tree_id: {context.tree_id}")

        # Check if the VARIANT-SCOPED cache exists (base cache being warm does
        # not imply the variant graph is — they are separate cache keys).
        cached_graph = get_cached_unified_graph(context.tree_id, context.team_id, variant=variant)

        if cached_graph:
            print(f"🚀 [_get_validation_plan] Using cached graph: {len(cached_graph.nodes)} nodes, {len(cached_graph.edges)} edges (FAST PATH, variant={variant or 'base'})")
        else:
            # Cache miss - load tree and populate cache
            print(f"📥 [_get_validation_plan] Cache miss - loading tree from database (SLOW PATH)")
            nav_result = device.navigation_executor.load_navigation_tree(
                args.userinterface,
                context.team_id
            )
            if not nav_result['success']:
                print(f"❌ [_get_validation_plan] Navigation tree loading failed")
                return []

            context.tree_data = nav_result

    return find_optimal_edge_validation_sequence(
        context.tree_id, context.team_id,
        subtree_root_node_id=subtree_root_node_id, variant=variant
    )


def capture_validation_summary(context, userinterface_name: str, max_iteration: int = None, subtree_root: str = None, variant: str = None) -> str:
    """Capture validation summary as text for report - uses actual recorded steps"""
    
    # Get actual step counts from context.step_results (not validation counters)
    # This ensures consistency between summary and detailed step list
    total_steps = len(context.step_results)
    successful_steps = sum(1 for step in context.step_results if step.get('success', False))
    failed_steps = total_steps - successful_steps
    
    # Get validation sequence stats for reference
    validation_iterations = getattr(context, 'validation_total_steps', 0)
    
    lines = []
    lines.append("-"*60)
    lines.append("🎯 [VALIDATION] EXECUTION SUMMARY")
    lines.append("-"*60)
    
    # Handle case where setup failed and device/host are None
    if context.selected_device:
        lines.append(f"📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
    else:
        lines.append(f"📱 Device: Setup failed - no device selected")
    
    if context.host:
        lines.append(f"🖥️ Host: {context.host.host_name}")
    else:
        lines.append(f"🖥️ Host: Setup failed - no host available")
    
    lines.append(f"📋 Interface: {userinterface_name}")
    lines.append(f"🎭 Variant: {variant or 'base'}")
    if subtree_root:
        lines.append(f"🌳 Subtree root: {subtree_root}")
    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    
    # Show validation iterations and actual navigation steps executed
    if max_iteration is not None:
        lines.append(f"🔢 Max Iteration Limit: {max_iteration} (validated {validation_iterations} transitions, executed {total_steps} navigation steps)")
    else:
        lines.append(f"🔢 Validated {validation_iterations} transitions (executed {total_steps} navigation steps)")
    
    lines.append(f"📊 Steps: {successful_steps}/{total_steps} steps successful")
    lines.append(f"✅ Successful: {successful_steps}")
    lines.append(f"❌ Failed: {failed_steps}")
    lines.append(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
    
    # Calculate coverage based on actual steps
    if total_steps > 0:
        coverage = (successful_steps / total_steps * 100)
        lines.append(f"🎯 Coverage: {coverage:.1f}%")
    else:
        lines.append(f"🎯 Coverage: 0.0% (no steps executed)")
    
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    
    if context.error_message:
        lines.append(f"\n❌ Error: {context.error_message}")
    
    lines.append("-"*60)

    return "\n".join(lines)


def capture_edge_results_summary(context) -> str:
    """Build the grouped Edge Results block (Successful / Failed / Skipped).

    Mirrors fullzap's `context.zap_detailed_summary` channel: a monospace text
    block rendered as its own collapsible section in the report. Reads the same
    `context.step_results` the summary counts come from, so the three buckets
    always add up to the headline numbers. A step is SKIPPED if it carries the
    `skipped` flag (set by `_record_skipped`), SUCCESSFUL if `success` is true,
    otherwise FAILED.
    """
    successful, failed, skipped = [], [], []
    for idx, step in enumerate(context.step_results, start=1):
        secs = (step.get('execution_time_ms') or 0) / 1000.0
        row = (
            idx,
            step.get('from_node', '?'),
            step.get('to_node', '?'),
            secs,
            (step.get('error') or '').strip(),
        )
        if step.get('skipped'):
            skipped.append(row)
        elif step.get('success'):
            successful.append(row)
        else:
            failed.append(row)

    lines = []

    def _section(title, rows, show_error):
        lines.append("-"*68)
        lines.append(f"{title} ({len(rows)})")
        lines.append("-"*68)
        if not rows:
            lines.append("  (none)")
            return
        for i, frm, to, secs, err in rows:
            lines.append(f"  #{i:<4}{frm:<16}→ {to:<20}{secs:>5.1f}s")
            if show_error and err:
                lines.append(f"        └─ {err}")

    _section("✅ SUCCESSFUL", successful, show_error=False)
    lines.append("")
    _section("❌ FAILED", failed, show_error=True)
    lines.append("")
    _section("⏭️ SKIPPED", skipped, show_error=True)

    return "\n".join(lines)


def validate_with_recovery(max_iteration: int = None, edges: str = None, subtree_root: str = None) -> bool:
    """Execute validation - test all transitions using NavigationExecutor directly"""
    context = get_context()

    # Variant resolution is now driven by an explicit --variant CLI flag (named
    # variants — see docs/agent/ENHANCE_VARIANT.md). The resolver reads the
    # variant from device.navigation_context['variant'], which the script
    # decorator populates from args.variant before this function runs.
    # locale_probe / device_locale / device_platform are NOT consulted from
    # this pipeline — they remain available as utilities for a future
    # auto-detection layer (§9 of ENHANCE_VARIANT.md).

    # Get validation plan (optionally scoped to a subtree)
    validation_sequence = _get_validation_plan(context, subtree_root_node_id=subtree_root)
    if not validation_sequence:
        context.error_message = (
            f"No validation sequence found for subtree root '{subtree_root}'"
            if subtree_root else "No validation sequence found"
        )
        print(f"❌ [validation] {context.error_message}")
        return False

    print(f"✅ [validation] Found {len(validation_sequence)} validation steps")

    # In subtree mode, pre-navigate the device to the subtree entry node so the
    # first edge in the filtered sequence starts from a reachable position.
    import asyncio
    if subtree_root:
        device = context.selected_device
        print(f"🌳 [validation] Subtree mode — navigating to subtree root '{subtree_root}'")
        nav_to_root = asyncio.run(device.navigation_executor.execute_navigation(
            tree_id=context.tree_id,
            target_node_id=subtree_root,
            userinterface_name=context.userinterface,
            team_id=context.team_id,
            context=context,
        ))
        if not nav_to_root.get('success'):
            context.error_message = f"Failed to navigate to subtree root '{subtree_root}': {nav_to_root.get('error', 'Unknown error')}"
            print(f"❌ [validation] {context.error_message}")
            return False
        print(f"✅ [validation] At subtree root — starting subtree validation")
    
    # Filter by selected step numbers if provided (skip if None or empty string).
    # The frontend sends 1-based step_numbers that match the preview iteration
    # order (mirrors server_validation_routes.py:get_validation_preview, which
    # assigns step_counter 1,2,... in iteration order over validation_sequence).
    if edges and edges.strip():
        try:
            selected_step_numbers = {int(s.strip()) for s in edges.split(',') if s.strip()}
        except ValueError:
            print(f"❌ [validation] --edges must be comma-separated integers (got: {edges!r})")
            return False
        original_count = len(validation_sequence)
        validation_sequence = [
            step for idx, step in enumerate(validation_sequence, start=1)
            if idx in selected_step_numbers
        ]
        print(f"🎯 [validation] Filtered to {len(validation_sequence)} selected steps (from {original_count} total)")
    
    # Apply max_iteration limit
    if max_iteration and max_iteration > 0:
        validation_sequence = validation_sequence[:max_iteration]
        print(f"🔢 [validation] Limited to {max_iteration} steps")

    context.total_steps = len(validation_sequence)
    context.emit_progress(message=f"Starting {len(validation_sequence)} transitions")

    # Nodes we proved unreachable this run — population is conservative: only
    # the immediate `from_node` of an edge whose pre-step pathfinding failed.
    # We deliberately do NOT cascade `to_node` membership; in DFS traversal the
    # same node appears as `from` and `to` many times, and one failed reposition
    # to a single-attempt target says nothing about reachability via other paths.
    unreachable_nodes = set()

    # Edge attempts that have already failed once this run, keyed by
    # (from_node_id, to_node_id, action_set_id). The optimal-walk planner emits
    # the same edge multiple times when it has to re-traverse to reach
    # different children; without this dedup, a single broken edge produces N
    # identical re-attempts (each preceded by a full ENTRY-→-…-→-from_node
    # reposition) that can only fail the same way. Action-set granularity
    # keeps alternative action_sets on the same edge eligible for a fresh try.
    failed_attempts = set()

    from datetime import datetime
    import asyncio

    device = context.selected_device

    def _record_skipped(step_idx, from_label, to_label, step_dict, reason):
        now_str = datetime.now().strftime('%H:%M:%S')
        skip_msg = f"Step {step_idx+1}/{len(validation_sequence)}: {from_label} → {to_label} ({reason})"
        print(f"⏭️ [validation] {skip_msg}")
        context.record_step_immediately({
            'success': False,
            'skipped': True,
            'from_node': from_label,
            'to_node': to_label,
            'message': f"{from_label} → {to_label}",
            'error': f"Skipped: {reason}",
            'execution_time_ms': 0,
            'start_time': now_str,
            'end_time': now_str,
            'actions': step_dict.get('actions', []),
            'verifications': step_dict.get('verifications', []),
            'step_category': 'navigation',
        })
        if hasattr(context, 'write_running_log'):
            context.write_running_log()
        context.emit_progress(
            message=skip_msg,
            step={
                'from_node': from_label,
                'to_node': to_label,
                'success': False,
                'error': f'Skipped: {reason}',
                'skipped': True,
            },
        )

    # Execute each transition. Two phases per step:
    #   1) reposition: if the device's tracked position differs from this step's
    #      `from_node`, navigate to it via real pathfinding (records the hops).
    #      `NavigationExecutor` clears its tracked position on every failure, so
    #      after an earlier verify fail this turns into "pathfind from entry".
    #   2) execute the precomputed step (single-edge action+verify).
    for i, step in enumerate(validation_sequence):
        target = step.get('to_node_label', 'unknown')
        from_node = step.get('from_node_label', 'unknown')
        from_node_id = step.get('from_node_id')
        to_node_id = step.get('to_node_id')
        action_set_id = step.get('action_set_id')

        if from_node_id in unreachable_nodes:
            _record_skipped(i, from_node, target, step,
                            f"'{from_node}' is unreachable from this run")
            continue

        if (from_node_id, to_node_id, action_set_id) in failed_attempts:
            _record_skipped(i, from_node, target, step,
                            f"edge attempt {from_node} → {target} already failed this run")
            continue

        # Phase 1: reposition to from_node if the device isn't already there.
        # `is_recovery=True` collapses the multi-step pathfinding into a single
        # "Recovery → X" row in the report (otherwise every intermediate hop
        # ENTRY → home → … → from_node shows up as its own row, e.g. 5 rows ×
        # N failed iterations = report wall-of-noise).
        nav_ctx = device.navigation_context
        current_pos = nav_ctx.get('current_node_id')
        if current_pos != from_node_id:
            print(f"🧭 [validation] Reposition before step {i+1}: → {from_node}")
            reposition_result = asyncio.run(device.navigation_executor.execute_navigation(
                target_node_id=from_node_id,
                tree_id=context.tree_id,
                userinterface_name=context.userinterface,
                team_id=context.team_id,
                context=context,
                is_recovery=True,
            ))
            if not reposition_result.get('success'):
                print(f"⚠️ [validation] Reposition to '{from_node}' failed — marking unreachable, skipping step")
                unreachable_nodes.add(from_node_id)
                _record_skipped(i, from_node, target, step,
                                f"could not reposition to '{from_node}'")
                continue

        # Phase 2: execute the precomputed step.
        print(f"⚡ [validation] Step {i+1}/{len(validation_sequence)}: {from_node} → {target}")
        result = asyncio.run(device.navigation_executor.execute_navigation(
            tree_id=context.tree_id,
            userinterface_name=context.userinterface,
            navigation_path=[step],
            team_id=context.team_id,
            context=context,
        ))

        step_success = bool(result.get('success', False))
        context.emit_progress(
            message=f"Step {i+1}/{len(validation_sequence)}: {from_node} → {target}",
            step={
                'from_node': from_node,
                'to_node': target,
                'success': step_success,
                'error': result.get('error') if not step_success else None,
            },
        )

        if step_success:
            print(f"✅ [validation] Step {i+1} successful")
        else:
            print(f"❌ [validation] Step {i+1} failed: {result.get('error', 'Unknown error')}")
            # NavigationExecutor has already cleared the tracked position on
            # failure. Mark `to_node` unreachable so the next iteration whose
            # `from_node` is this destination skips immediately without firing
            # another reposition (which would just re-walk ENTRY → home → … →
            # to_node and fail at the same edge). On a transient failure where
            # the next step's `from_node` is *different* and reachable, the
            # Phase-1 reposition still fires normally for it.
            unreachable_nodes.add(to_node_id)
            # Also dedup the exact (from, to, action_set) attempt so that
            # later repeats of the same edge in the planner's sequence skip
            # immediately. Action-set granularity preserves the option of
            # trying a different action_set on the same edge if one ever
            # appears later.
            failed_attempts.add((from_node_id, to_node_id, action_set_id))
    
    # Calculate success directly from context.step_results (matches summary logic)
    total_steps = len(context.step_results)
    successful_steps = sum(1 for step in context.step_results if step.get('success', False))
    
    context.validation_successful_steps = successful_steps
    context.validation_total_steps = len(validation_sequence)
    
    # Set overall success based on actual recorded steps
    context.overall_success = (successful_steps == total_steps and total_steps > 0)
    
    coverage = (successful_steps / total_steps * 100) if total_steps else 0
    print(f"🎉 [validation] Results: {successful_steps}/{total_steps} steps successful ({coverage:.1f}%)")
    return context.overall_success


@script("validation", "Validate navigation tree transitions", default_device="device1")
def main():
    """Main validation function - simple and clean"""
    context = get_context()
    args = get_args()
    
    # Execute validation with selected edges if provided
    subtree_root = getattr(args, 'subtree_root', None) or None
    result = validate_with_recovery(args.max_iteration, args.edges, subtree_root)

    # Resolve the active variant the same way _get_validation_plan does
    # (device.navigation_context is canonical; args is the fallback).
    device = context.selected_device
    variant = None
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if not variant:
        variant = getattr(args, 'variant', None)
    if isinstance(variant, str):
        variant = variant.strip() or None

    # Always capture summary for report (regardless of success/failure)
    summary_text = capture_validation_summary(
        context, args.userinterface, args.max_iteration,
        subtree_root=subtree_root, variant=variant
    )
    context.execution_summary = summary_text

    # Grouped Success/Failed/Skipped edge breakdown for its own report section
    # (rendered like fullzap's zap summary). Built from the same step_results.
    context.edge_results_summary = capture_edge_results_summary(context)

    return result


# Bind module-level metadata to the decorated `main` (declared at top of file).
main._script_args = _script_args
main._script_description = _script_description
main._arg_descriptions = _arg_descriptions

if __name__ == "__main__":
    main()

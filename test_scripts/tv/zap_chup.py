#!/usr/bin/env python3
"""
Zap Chup - Channel Zapping Test Script

Executes an action node multiple times to test:
1. First call: Full navigation (entry → parent → action)
2. Subsequent calls: Optimized direct action execution (already at parent)

Usage:
    python test_scripts/tv/zap_chup.py [--iterations <count>] [--node <action_node>]
    
Examples:
    python test_scripts/tv/zap_chup.py --iterations 5                    # Zap 5 times
    python test_scripts/tv/zap_chup.py --node live_chup --iterations 10  # Custom action, 10 times
    python test_scripts/tv/zap_chup.py example_mobile --node live_chdown --iterations 3
"""

import sys
import os
import asyncio
import time

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.executors.zap_executor import ZapExecutor

# Seconds to let the destination channel settle before checking motion. Without a
# zapping-detection poll (zap_chup is a navigation/optimization test), this gives
# the capture pipeline time to render + analyze the destination frames so we read
# the settled channel rather than the blackscreen transition.
MOTION_SETTLE_SECONDS = 3


@script("zap_chup", "Execute action node multiple times", default_device="device1")
def main():
    """Execute action node multiple times with optimization tracking"""
    args = get_args()
    context = get_context()
    target_node = args.node
    iterations = int(args.iterations)
    device = get_device()
    
    print(f"\n{'='*60}")
    print(f"📺 ZAP CHUP - Channel Zapping Test")
    print(f"{'='*60}")
    print(f"🎯 Action node: {target_node}")
    print(f"🔄 Iterations: {iterations}")
    print(f"📱 Device: {device.device_name} ({device.device_model})")
    print(f"{'='*60}\n")
    
    # Load navigation tree
    nav_result = device.navigation_executor.load_navigation_tree(
        args.userinterface, 
        context.team_id
    )
    if not nav_result['success']:
        context.error_message = f"Navigation tree loading failed: {nav_result.get('error', 'Unknown error')}"
        return False
    
    context.tree_id = nav_result['tree_id']

    # Resolve the action node's friendly display name (data.display_name, e.g.
    # "Channel Up"). Used to name the run in the report; falls back to the raw
    # node label when unset. Same shared resolver standby_measurement uses.
    from shared.src.lib.database.navigation_trees_db import get_node_display_name
    node_display = get_node_display_name(context.tree_id, context.team_id, target_node)
    node_name = node_display or target_node
    if node_display:
        print(f"🏷️  Display name: {node_name}  (node: {target_node})")

    # Reuse ZapExecutor's strict real motion detection (any frozen/blackscreen frame ⇒ no
    # motion) to verify the destination is actually playing after each zap. A wider compare
    # window (up to the helper's 2.0s cap) gives slow/near-static live content more chance to
    # move, cutting false "not playing" misses; motion_threshold tunes the change % needed.
    motion_threshold = max(0.0, float(args.motion_threshold))
    motion_window = min(2.0, max(0.0, float(args.motion_window_s)))
    print(f"🎚️  Motion threshold: {motion_threshold}% change | window: {motion_window:.1f}s")
    zap_executor = ZapExecutor(device, args.userinterface,
                               motion_threshold=motion_threshold, motion_duration=motion_window)

    # Track results for all iterations
    results = []
    
    # Forward the node's friendly display name to the KPI rows. NavigationExecutor
    # reads this off navigation_context and threads it into every KPI request
    # queued during this run, so the KPI dashboard labels the row '[TC258] Channel
    # Up' instead of the raw edge label. Cleared in the finally below — the dict
    # lives on the long-lived Device, so a leak would mislabel later scripts.
    if node_display and getattr(device, 'navigation_context', None) is not None:
        device.navigation_context['kpi_display_label'] = node_name

    try:
        for i in range(iterations):
            iteration_num = i + 1
            is_first = (i == 0)
        
            print(f"\n{'='*60}")
            print(f"📍 ITERATION {iteration_num}/{iterations}: '{node_name}'")
            if is_first:
                print(f"   Expected: Full navigation (entry → parent → action)")
            else:
                print(f"   Expected: Direct action (already at parent)")
            print(f"{'='*60}\n")
        
            result = asyncio.run(device.navigation_executor.execute_navigation(
                tree_id=context.tree_id,
                userinterface_name=context.userinterface,
                target_node_label=target_node,
                team_id=context.team_id,
                context=context
            ))
        
            transitions = result.get('total_transitions', 0)
            nav_success = result.get('success', False)
            final_pos = result.get('final_position_node_id', 'N/A')

            # Show the friendly display name on the zap step row. The final step
            # recorded by execute_navigation lands on target_node; rewrite only its
            # destination segment ("… → live_chup" → "… → Channel Up"), keeping the
            # raw label on the from-side intact.
            if node_display and context.step_results:
                last_step = context.step_results[-1]
                msg = last_step.get('message') or ''
                if ' → ' in msg:
                    left = msg.rsplit(' → ', 1)[0]
                    last_step['message'] = f"{left} → {node_name}"
                last_step['to_node'] = node_name

            # After a successful zap, verify the destination is actually playing video
            # (not a frozen / parental-block screen). The navigation reporting success
            # only means the key was sent and the path executed.
            motion_detected = False
            real_motion = None
            if nav_success:
                time.sleep(MOTION_SETTLE_SECONDS)
                # Real frame-to-frame motion (2 fresh captures), not the JSON freeze flag.
                # detect_real_motion returns its result dict whether or not motion was found
                # (it carries change% + compared frames even on a miss), so the verdict is
                # real_motion['motion'], NOT the truthiness of the dict.
                real_motion = zap_executor.detect_real_motion(context)
                motion_detected = bool(real_motion and real_motion.get('motion'))
                # Surface the motion verdict on the zap step so the report shows the
                # 'Motion Detection: DETECTED / NOT DETECTED' line + compared frames
                # (parity with zap_digit). detect_real_motion already added the frames.
                if real_motion is not None and context.step_results:
                    context.step_results[-1]['motion_analysis'] = {
                        'success': bool(real_motion.get('motion')),
                        'change_percentage': real_motion.get('change'),
                        'real_motion_change': real_motion.get('change'),
                        'real_motion_threshold': real_motion.get('threshold'),
                        'real_motion_area': real_motion.get('area'),
                        'motion_analysis_images': real_motion.get('images') or [],
                    }

            # The very first iteration is a warm-up: content can be nearly static (e.g. a
            # paused sports scene) and score below the motion threshold even though the
            # destination IS playing. Treat that first-iteration miss as non-blocking so it
            # doesn't fail the run or lose the KPI measurement — later iterations stay strict.
            non_blocking = is_first and nav_success and not motion_detected

            # An iteration passes only if it navigated AND the destination is playing.
            success = nav_success and motion_detected
            # The zap step badge should reflect the REAL result (nav AND motion), not just
            # navigation — a frozen destination is a failed zap. A non-blocking first-iteration
            # miss still shows PASS.
            if context.step_results:
                context.step_results[-1]['success'] = success or non_blocking

            # Best-effort: pull the local zap measurement vpt-monitor wrote for this zap
            # (channel + durations), matched by the action timestamp the navigation/action
            # executor stamped into last_action.json. Same read fullzap uses.
            measurement = None
            if nav_success:
                nav_ctx = getattr(device, 'navigation_context', None) or {}
                action_ts = nav_ctx.get('last_action_timestamp')
                if action_ts:
                    measurement = zap_executor.fetch_zap_measurement(context, action_ts)
                    # Attach to the navigation step that did the zap so it shows in the
                    # report under "Analysis Results → Zap Detection".
                    if measurement and context.step_results:
                        context.step_results[-1]['zapping_analysis'] = {
                            'success': True,
                            'zapping_detected': True,
                            'total_zap_duration_ms': measurement.get('total_zap_duration_ms') or 0,
                            'blackscreen_duration_ms': measurement.get('blackscreen_duration_ms') or 0,
                            'transition_type': 'freeze' if measurement.get('detection_type') == 'freeze' else 'blackscreen',
                            # Link to this zap's standalone measurement report (rendered as a
                            # "View Zap Report" link in the step's Zap Detection block).
                            'report_url': measurement.get('report_url'),
                            'channel_info': {
                                'channel_name': measurement.get('channel_name', ''),
                                'channel_number': measurement.get('channel_number', ''),
                                'program_name': measurement.get('program_name', ''),
                            },
                        }
                    # Remember the latest per-event zap report URL for the summary header link.
                    if measurement and measurement.get('report_url'):
                        if getattr(context, 'custom_data', None) is None:
                            context.custom_data = {}
                        context.custom_data['zap_report_url'] = measurement['report_url']

            results.append({
                'iteration': iteration_num,
                'success': success,
                'non_blocking': non_blocking,
                'nav_success': nav_success,
                'motion_detected': motion_detected,
                'transitions': transitions,
                'final_position': final_pos,
                'measurement': measurement,
            })

            if motion_detected:
                motion_label = '✅ DETECTED'
            elif non_blocking:
                motion_label = '⚠️ NOT DETECTED (first iteration — not blocking)'
            else:
                motion_label = '❌ NOT DETECTED'
            print(f"\n📊 Iteration {iteration_num} result:")
            print(f"   Navigation: {'✅' if nav_success else '❌'}")
            print(f"   Motion (destination playing): {motion_label}")
            if measurement:
                total_ms = measurement.get('total_zap_duration_ms')
                duration_str = f" | total {total_ms}ms" if total_ms else ""
                print(f"   Zap measured: ch {measurement.get('channel_number') or '?'} "
                      f"{measurement.get('channel_name', '')}{duration_str}")
            print(f"   Transitions: {transitions}")
            print(f"   Final position: {final_pos}")

            # Only a BLOCKING failure sets the run error. The first iteration's near-static
            # motion miss is non-blocking (destination playing, just static).
            if not success and not non_blocking:
                if not nav_success:
                    context.error_message = f"Iteration {iteration_num} failed: {result.get('error')}"
                else:
                    context.error_message = f"Iteration {iteration_num} failed: destination frozen (no motion detected)"
                # Continue anyway to see full results
    finally:
        if getattr(device, 'navigation_context', None):
            device.navigation_context.pop('kpi_display_label', None)
    
    # ============================================
    # SUMMARY
    # ============================================
    # Active variant for this run (device.navigation_context is canonical,
    # set unconditionally by the script executor; args is the fallback).
    variant = None
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if not variant:
        variant = getattr(args, 'variant', None)
    if isinstance(variant, str):
        variant = variant.strip() or None

    print(f"\n{'='*60}")
    print(f"🎯 ZAP CHUP SUMMARY")
    print(f"{'='*60}")
    print(f"   📋 Interface: {args.userinterface}")
    print(f"   🎭 Variant: {variant or 'base'}")
    print(f"   🏷️ Action: {node_name}")

    successful = sum(1 for r in results if r['success'])
    non_blocking_count = sum(1 for r in results if r.get('non_blocking'))
    # "Frozen" = genuinely frozen blocking iterations (the non-blocking first-iteration miss
    # is reported separately so it isn't double-counted here).
    frozen_count = sum(1 for r in results
                       if r['nav_success'] and not r['motion_detected'] and not r.get('non_blocking'))
    measured_count = sum(1 for r in results if r.get('measurement'))
    first_transitions = results[0]['transitions'] if results else 0
    optimized_count = sum(1 for r in results[1:] if r['transitions'] == 1)

    print(f"\n   📊 Results by iteration:")
    for r in results:
        status = "✅" if r['success'] else ("⚠️" if r.get('non_blocking') else "❌")
        nav = "nav✅" if r['nav_success'] else "nav❌"
        motion = "motion✅" if r['motion_detected'] else "motion❌"
        opt = "⚡" if r['transitions'] == 1 and r['iteration'] > 1 else ""
        meas = r.get('measurement')
        meas_str = ""
        if meas:
            total_ms = meas.get('total_zap_duration_ms')
            meas_str = f"  📺 {meas.get('channel_number') or '?'} {meas.get('channel_name', '')}"
            if total_ms:
                meas_str += f" ({total_ms}ms)"
        print(f"      {r['iteration']:2d}. {status} [{nav} {motion}] {r['transitions']} transitions {opt}{meas_str}")

    print(f"\n   📈 Statistics:")
    print(f"      Total iterations: {iterations}")
    print(f"      Successful (motion confirmed): {successful}")
    if non_blocking_count:
        print(f"      Non-blocking first-iteration misses: {non_blocking_count}")
    print(f"      Frozen destination (zapped but no motion): {frozen_count}")
    print(f"      Zap measurements fetched: {measured_count}/{len(results)}")
    print(f"      First navigation: {first_transitions} transitions")
    
    if iterations > 1:
        print(f"      Optimized calls: {optimized_count}/{iterations-1} (expected: {iterations-1})")
        
        if optimized_count == iterations - 1:
            print(f"\n   ✅ OPTIMIZATION WORKING! All subsequent calls were direct (1 step)")
        elif optimized_count > 0:
            print(f"\n   ⚠️  Partial optimization: {optimized_count} of {iterations-1} calls optimized")
        else:
            print(f"\n   ❌ No optimization detected")
    
    print(f"{'='*60}\n")
    
    # Success = at least one zap played AND no blocking frozen zap. The first iteration's
    # near-static motion miss is non-blocking (warm-up), so it doesn't fail the run.
    # Iterations that never reached live (nav retry) didn't zap → ignored.
    context.overall_success = (successful >= 1) and (frozen_count == 0)
    nb_note = f", {non_blocking_count} non-blocking first-iteration" if non_blocking_count else ""
    context.execution_summary = f"Zap test [{node_name} @ {args.userinterface}/{variant or 'base'}]: {successful}/{iterations} successful, {frozen_count} frozen{nb_note}, {optimized_count}/{max(iterations-1,1)} optimized"
    return context.overall_success


# Script arguments
main._script_args = [
    '--userinterface:str:example_mobile',
    '--variant:str:',            # Optional named variant; empty = base
    '--node:str:live_chup',      # Default action node
    '--iterations:int:3',         # Default to 3 iterations
    '--motion-threshold:float:1.0',   # Min frame-to-frame change % to count as motion
    '--motion-window-s:float:2.0',    # Seconds between the two compared frames (max 2.0)
]
main._script_description = "Execute channel zap action multiple times."
main._arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': "Optional variant name; if omitted, base data is used.",
    'node': 'Action node to execute',
    'iterations': 'Number of zap repetitions',
    'motion-threshold': 'Minimum frame-to-frame change percentage to count the destination as playing. Lower it when valid content is nearly static; raise it to reject overlay-only movement.',
    'motion-window-s': 'Seconds between the two frames the motion check compares (capped at 2.0). A wider window gives slow/near-static content more chance to move, reducing false "not playing" misses.',
}
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()

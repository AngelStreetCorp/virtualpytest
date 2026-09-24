#!/usr/bin/env python3
"""
Generic Navigation Script for VirtualPyTest

This script navigates to a specified node in the navigation tree.
If no node is specified, it defaults to 'home'.

Every argument is a flag — there is no positional userinterface argument. A bare
positional is ignored and --userinterface silently keeps its default, so the run
loads the wrong tree.

Usage:
    python test_scripts/goto.py [--userinterface <name>] [--node <node_name>]
                                [--device <device_id>] [--variant <name>]
                                [--verify end|each|auto]

Examples:
    python test_scripts/goto.py                           # Goes to 'home' node
    python test_scripts/goto.py --node live               # Goes to 'live' node
    python test_scripts/goto.py --userinterface example_mobile --node settings
    python test_scripts/goto.py --userinterface example_androidtv --node live_fullscreen --device device2
"""

import sys
import os

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device


def capture_navigation_summary(context, userinterface_name: str, target_node: str, already_at_destination: bool = False, variant: str = None) -> str:
    """Capture navigation summary as text for report"""
    lines = []
    lines.append(f"🎯 [GOTO_{target_node.upper()}] EXECUTION SUMMARY")
    # Device/host may be unset on a very early abort — keep the summary
    # renderable regardless (mirrors validation.py / kpi_measurement.py).
    if context.selected_device:
        lines.append(f"📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
    else:
        lines.append("📱 Device: Setup failed - no device selected")
    if context.host:
        lines.append(f"🖥️ Host: {context.host.host_name}")
    else:
        lines.append("🖥️ Host: Setup failed - no host available")
    lines.append(f"📋 Interface: {userinterface_name}")
    lines.append(f"🎭 Variant: {variant or 'base'}")
    lines.append(f"🗺️ Target: {target_node}")
    
    if already_at_destination:
        lines.append(f"✅ Already at destination - no navigation needed")
        lines.append(f"📍 Navigation steps: 0 (already verified at target)")
    else:
        lines.append(f"📍 Navigation steps: {len(context.step_results)}")
    
    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    
    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    
    return "\n".join(lines)


@script("goto", "Navigate to specified node", default_device="device1")
def main():
    """Main navigation function to goto specified node.

    The execution summary (incl. Interface + Variant) is built in `finally`
    so it is emitted on every exit path — success, navigation failure, the
    early tree-load `return False`, and unhandled exceptions. Previously the
    early tree-load failure / an exception left the report showing
    "Execution summary not available".
    """
    args = get_args()
    context = get_context()
    target_node = args.node
    device = get_device()
    print(f"🎯 [goto] Target node: {target_node}")
    print(f"📱 [goto] Device: {device.device_name} ({device.device_model})")

    # Resolve the active variant (device.navigation_context is canonical;
    # args is the fallback). None / '' = base.
    variant = None
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if not variant:
        variant = getattr(args, 'variant', None)
    if isinstance(variant, str):
        variant = variant.strip() or None

    already_at_destination = False
    try:
        # Load navigation tree
        nav_result = device.navigation_executor.load_navigation_tree(
            args.userinterface,
            context.team_id
        )
        if not nav_result['success']:
            context.error_message = f"Navigation tree loading failed: {nav_result.get('error', 'Unknown error')}"
            context.overall_success = False
            return False

        context.tree_id = nav_result['tree_id']

        # Verification mode (CLI: --verify end|each|auto, default end).
        # Mirrors the dropdown on the frontend Goto panel.
        verification_mode = (getattr(args, 'verify', 'end') or 'end').strip().lower()
        if verification_mode not in ('end', 'each', 'auto'):
            verification_mode = 'end'

        # Execute navigation using NavigationExecutor directly
        # ✅ Wrap async call with asyncio.run for script context
        import asyncio
        result = asyncio.run(device.navigation_executor.execute_navigation(
            tree_id=context.tree_id,
            userinterface_name=context.userinterface,  # MANDATORY parameter
            target_node_label=target_node,
            team_id=context.team_id,
            context=context,
            verification_mode=verification_mode,
        ))

        success = result.get('success', False)
        if not success:
            context.error_message = result.get('error', 'Navigation failed')

        # Set overall_success BEFORE capturing summary so it shows correct status
        context.overall_success = success

        # Check if already at destination (no steps recorded)
        already_at_destination = (len(context.step_results) == 0 and success)

        return success
    finally:
        # Always capture summary for report (every exit path).
        context.execution_summary = capture_navigation_summary(
            context, args.userinterface, target_node, already_at_destination, variant=variant
        )

# Script arguments (framework params have defaults, script params are specific)
main._script_args = [
    '--userinterface:str:example_mobile',  # Framework param with default
    '--variant:str:',                              # Optional named variant; empty = base
    '--node:str:home',                             # Script-specific param
    '--verify:str:end:end|each|auto',              # Verification mode dropdown
]
main._script_description = "Navigate to any node in the navigation tree."
main._arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': "Optional variant name; if omitted, base data is used.",
    'node': 'Target node to navigate to',
    'verify': "Verification mode: 'end' (default, only destination), 'each' (every step), 'auto' (skip steps with edge+node confidence ≥ 0.7).",
}
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()

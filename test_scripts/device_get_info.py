#!/usr/bin/env python3
"""
Go to Info Node Script for VirtualPyTest

This script navigates to the 'info' node in the navigation tree (default),
dumps the page elements, extracts device information, and stores it in metadata.

Usage:
    python test_scripts/get_info.py [userinterface_name] [--node <node_name>]
    
Examples:
    python test_scripts/get_info.py                           # Goes to 'info' node (default)
    python test_scripts/get_info.py --node info_settings      # Goes to 'info_settings' node
    python test_scripts/get_info.py example_mobile --node info
    python test_scripts/get_info.py example_androidtv --node info_settings --device device2
"""

import sys
import os
import re
from typing import Dict, Any, List, Optional

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)  # test_scripts/ -> project root
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device

# Script arguments
# MUST be defined near top of file (within first 300 lines) for script analyzer
# Script arguments (framework params have defaults, script params are specific)
_script_args = [
    '--userinterface:str:example_gui',  # Framework param with default
    '--variant:str:',               # Optional named variant; empty = base
    '--node:str:info',              # Script-specific param
    # Default value is the full built-in whitelist (kept in sync with
    # OCR_CHAR_WHITELIST below) so RunTests prefills it and the user can see/edit
    # the characters OCR is allowed to emit. The analyzer strips leading/trailing
    # whitespace, so the space sits mid-string (the whitelist is a char *set* —
    # order is irrelevant to tesseract). Empty still falls back to the constant.
    '--ocr_whitelist:str:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz 0123456789.-_+',
]
_script_description = "Navigate to info screen and extract device data."
_arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': "Optional variant name; if omitted, base data is used.",
    'node': 'Target info node to navigate to',
    'ocr_whitelist': "Characters OCR is allowed to emit. Prefilled with the built-in "
                     "default (alphanumerics + . - _ + and space), which stops OCR from "
                     "inventing stray symbols in version/serial strings. Edit per run, "
                     "or clear to fall back to the same built-in default.",
}

# Default tesseract char whitelist for the info screen. Forces OCR to emit ONLY
# these characters so it can't misread noise as punctuation/symbols. The set is
# alphanumeric + ".-_+" plus a space (space sits mid-string, not at an edge, so
# the analyzer that prefills --ocr_whitelist in RunTests can't strip it). This is
# the CLI fallback when --ocr_whitelist is empty and MUST match the default in
# _script_args above. Override per run with --ocr_whitelist when a device shows
# fields with other separators.
OCR_CHAR_WHITELIST = (
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    'abcdefghijklmnopqrstuvwxyz'
    ' '
    '0123456789'
    '.-_+'
)


# ✅ getMenuInfo action handles all parsing via ExecutionOrchestrator
# Controller returns parsed_data directly - no manual parsing needed


def resolve_variant(context, device=None) -> Optional[str]:
    """Active variant for this run, or None for base.

    device.navigation_context is canonical (set unconditionally by the script
    executor); args is the fallback. Falls back to context.selected_device when
    no device is passed.
    """
    device = device if device is not None else context.selected_device
    variant = None
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if not variant:
        variant = getattr(getattr(context, 'args', None), 'variant', None)
    if isinstance(variant, str):
        variant = variant.strip() or None
    return variant


def capture_navigation_summary(context, userinterface_name: str, target_node: str, already_at_destination: bool = False, metadata: Dict[str, Any] = None) -> str:
    """Capture navigation summary as text for report"""
    variant = resolve_variant(context)

    lines = []
    lines.append(f"🎯 [GET_INFO] EXECUTION SUMMARY")
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
    
    # Add device info extraction with parsed data display (like dns_lookuptime.py)
    if metadata and 'info' in metadata:
        parsed_data = metadata['info']
        element_count = metadata.get('element_count', 0)
        
        lines.append(f"\n{'='*80}")
        lines.append(f"📊 DEVICE INFO PARSED RESULTS")
        lines.append(f"{'='*80}")
        lines.append(f"🔍 Elements Scanned: {element_count}")
        lines.append(f"📝 Fields Extracted: {len(parsed_data)}")
        lines.append(f"")
        
        if parsed_data:
            lines.append(f"📋 EXTRACTED DEVICE DATA:")
            for field_name, field_value in parsed_data.items():
                # Format field name nicely (replace underscores with spaces, capitalize)
                display_name = field_name.replace('_', ' ').title()
                lines.append(f"   • {display_name}: {field_value}")
        else:
            lines.append(f"⚠️  No device info fields extracted (check info page format)")
        
        lines.append(f"{'='*80}")
    
    lines.append(f"\n🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    
    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    
    return "\n".join(lines)


# Retry policy: this script reports the software under test, so a transient
# failure (e.g. a sleeping box / BLE remote that hasn't woken yet) must not be
# taken at face value. Retry the whole navigation + extraction up to
# MAX_ATTEMPTS times, waiting RETRY_DELAY_S after each failure to give the
# device time to wake up. Only real failures (tree-load / navigation) retry;
# the "no parsed_data" warning paths already succeed.
MAX_ATTEMPTS = 3
RETRY_DELAY_S = 40


def _run_attempt(context, device, target_node, char_whitelist=None):
    """Run one navigation + extraction attempt.

    Returns (success, already_at_destination). On a real failure (tree-load or
    navigation) returns (False, False) with context.error_message set; on
    success — including the parsed_data-missing warning paths — returns
    (True, already_at_destination).
    """
    # Load navigation tree
    nav_result = device.navigation_executor.load_navigation_tree(
        context.userinterface,
        context.team_id
    )
    if not nav_result['success']:
        context.error_message = f"Navigation tree loading failed: {nav_result.get('error', 'Unknown error')}"
        context.overall_success = False
        return False, False

    context.tree_id = nav_result['tree_id']

    # Execute navigation using NavigationExecutor directly
    # ✅ Wrap async call with asyncio.run for script context
    import asyncio
    result = asyncio.run(device.navigation_executor.execute_navigation(
        tree_id=context.tree_id,
        userinterface_name=context.userinterface_name,  # MANDATORY parameter
        target_node_label=target_node,
        team_id=context.team_id,
        context=context
        #verification_mode='each'  # verify every step, not just the last (default 'end')
    ))

    success = result.get('success', False)
    if not success:
        context.error_message = result.get('error', 'Navigation failed')
        context.overall_success = False
        return False, False

    # Navigation successful - now extract device info
    already_at_destination = (len(context.step_results) == 0 and success)

    print(f"\n📋 [get_info] ==========================================")
    print(f"📋 [get_info] EXTRACTING DEVICE INFORMATION")
    print(f"📋 [get_info] ==========================================\n")

    # ✅ Use ExecutionOrchestrator pattern (same as frontend UniversalBlock)
    # Determine verification_type based on device model
    device_model = device.device_model.lower()
    if 'android_mobile' in device_model:
        verification_type = 'adb'  # ADB for Android mobile
    elif 'host_vnc' in device_model:
        verification_type = 'web'  # Playwright for host VNC
    else:
        verification_type = 'text'  # OCR for all others (video, audio, etc.)

    print(f"📋 [get_info] Detected verification_type: {verification_type} for device model: {device_model}")

    # Build action with verification (same format as frontend UniversalBlock)
    action = {
        'command': 'getMenuInfo',
        'name': 'Get Menu Info',  # EdgeAction requires name field
        'params': {
            'area': None,  # Full screen extraction
            # Force OCR to only emit these characters (tessedit_char_whitelist).
            # Only meaningful for the text/OCR path; ignored by adb/web.
            'ocr_whitelist': char_whitelist,
        },
        'action_type': 'verification',  # ✅ Treat verification as action (routes through orchestrator)
        'verification_type': verification_type,
    }

    print(f"📋 [get_info] Device model: {device.device_model}")
    print(f"📋 [get_info] Executing getMenuInfo as action via ExecutionOrchestrator...")

    # Execute through ActionExecutor (same as frontend) - orchestrator routes to verification executor
    from backend_host.src.orchestrator.execution_orchestrator import ExecutionOrchestrator

    # ✅ Wrap async call with asyncio.run for script context
    action_result = asyncio.run(ExecutionOrchestrator.execute_actions(
        device=device,
        actions=[action],
        team_id=context.team_id,
        context=context
    ))

    if not action_result.get('success'):
        error_msg = action_result.get('error', 'getMenuInfo action failed')
        print(f"⚠️  [get_info] Warning: {error_msg}")
        context.overall_success = True
        return True, already_at_destination

    # Extract output_data from action result (same as frontend UniversalBlock line 368)
    output_data = action_result.get('output_data', {})
    if not output_data:
        # Try results array format
        results = action_result.get('results', [])
        if results:
            output_data = results[0].get('output_data', {})

    parsed_data = output_data.get('parsed_data', {})
    element_count = output_data.get('element_count', 0)

    if not parsed_data:
        print(f"⚠️  [get_info] Warning: No parsed_data in output")
        context.overall_success = True
        return True, already_at_destination

    print(f"✅ [get_info] Action completed: {len(parsed_data)} fields extracted from {element_count} elements")

    # Step 3: Store to context.metadata['info'] (aligned with testcase builder)
    from datetime import datetime
    extraction_timestamp = datetime.fromtimestamp(context.start_time).isoformat() if hasattr(context, 'start_time') and context.start_time else None

    # NESTED structure: parsed_data goes under 'info' key
    context.metadata = {
        "info": parsed_data,  # Controller's parsed_data
        "variant": resolve_variant(context, device),  # None = base run
        "extraction_timestamp": extraction_timestamp,
        "extraction_method": "script",
        "device_name": device.device_name,
        "device_model": device.device_model,
        "host_name": context.host.host_name,
        "userinterface_name": context.userinterface,
        "element_count": element_count,
    }

    print(f"\n✅ [get_info] Device info extraction complete!")
    print(f"✅ [get_info] Metadata will be saved to script_results.metadata column")
    print(f"✅ [get_info] Structure: metadata['info'] = {list(parsed_data.keys())}")

    # Set overall_success BEFORE capturing summary
    context.overall_success = True

    return True, already_at_destination


@script("device_get_info", "Navigate to info node and extract device information", default_device="device1", capture_artifacts=False)
def main():
    """Main function: navigate to info node, extract device info, and store in metadata.

    The navigation + extraction runs through `_run_attempt`, retried up to
    MAX_ATTEMPTS times with a RETRY_DELAY_S pause after each failure — this is
    a critical script (it identifies the software under test), so a sleeping
    box / waking BLE remote shouldn't produce a false failure.

    The execution summary (incl. Interface + Variant) is built in `finally`
    so it is emitted on every exit path — success, navigation failure, the
    early tree-load failure, and unhandled exceptions (navigation /
    orchestrator). Previously the early tree-load failure / an exception
    left the report showing "Execution summary not available".
    """
    import time

    args = get_args()
    context = get_context()
    target_node = args.node
    device = get_device()
    # Empty arg → built-in default whitelist. Lets OCR be constrained by default
    # while still allowing a per-run override.
    char_whitelist = (getattr(args, 'ocr_whitelist', '') or '').strip() or OCR_CHAR_WHITELIST
    print(f"🎯 [get_info] Target node: {target_node}")
    print(f"📱 [get_info] Device: {device.device_name} ({device.device_model})")
    print(f"🔤 [get_info] OCR char whitelist: {char_whitelist!r}")

    already_at_destination = False
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            # Clear per-attempt failure state so the report reflects the
            # successful (or final) attempt, not accumulated retries.
            context.error_message = None
            if isinstance(getattr(context, 'step_results', None), list):
                context.step_results.clear()
            if isinstance(getattr(context, 'screenshot_paths', None), list):
                context.screenshot_paths.clear()

            print(f"🔁 [get_info] Attempt {attempt}/{MAX_ATTEMPTS}")
            success, already_at_destination = _run_attempt(context, device, target_node, char_whitelist)
            if success:
                return True

            # Real failure (tree-load / navigation). Retry after a wake-up
            # pause unless this was the last attempt.
            if attempt < MAX_ATTEMPTS:
                print(
                    f"⚠️  [get_info] Attempt {attempt}/{MAX_ATTEMPTS} failed: "
                    f"{context.error_message}. Waiting {RETRY_DELAY_S}s before retry "
                    f"(letting a sleeping box / BLE remote wake up)..."
                )
                time.sleep(RETRY_DELAY_S)
            else:
                print(f"❌ [get_info] All {MAX_ATTEMPTS} attempts failed: {context.error_message}")
                context.overall_success = False
                return False

        return False
    finally:
        # Always capture summary for report (every exit path). metadata is
        # only set on the full-success path; capture_navigation_summary
        # renders the device-info block only when it's present.
        context.execution_summary = capture_navigation_summary(
            context, context.userinterface, target_node,
            already_at_destination, getattr(context, 'metadata', None)
        )

# Assign script arguments to main function
main._script_args = _script_args
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
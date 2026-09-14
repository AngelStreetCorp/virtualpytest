#!/usr/bin/env python3

import sys
import os
import time
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_device, get_args, get_context

def print_fullzap_summary(context, userinterface_name: str):
    device = get_device()
    # Active variant for this run (device.navigation_context is canonical,
    # set unconditionally by the script executor; args is the fallback).
    variant = None
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if not variant:
        variant = getattr(getattr(context, 'args', None), 'variant', None)
    if isinstance(variant, str):
        variant = variant.strip() or None
    print("\n" + "="*60)
    print(f"🎯 [FULLZAP] EXECUTION SUMMARY")
    print("="*60)
    print(f"📱 Device: {device.device_name} ({device.device_model})")
    print(f"🖥️ Host: {context.host.host_name}")
    print(f"📋 Interface: {userinterface_name}")
    print(f"🎭 Variant: {variant or 'base'}")
    print(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    print(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
    print(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    
    if hasattr(context, 'error_message') and context.error_message:
        print(f"❌ Error: {context.error_message}")
    
    print("="*60)

def parse_motion_area(area_str: str):
    """Parse a '--motion-area' value 'x,y,width,height' into a dict, or None if empty/invalid.

    The area restricts the post-zap REAL motion check to a content region so an animated
    overlay (clock / progress bar / EPG banner) doesn't make a frozen channel read as motion.
    When omitted (None), the detector defaults to the CENTRE 60% of the frame — which already
    excludes typical header/footer/side overlays. Only set this to tune the region per UI.
    """
    if not area_str or not area_str.strip():
        return None
    try:
        x, y, w, h = [int(p.strip()) for p in area_str.split(',')]
        return {'x': x, 'y': y, 'width': w, 'height': h}
    except (ValueError, AttributeError):
        print(f"⚠️ [fullzap] Invalid --motion-area '{area_str}' (expected 'x,y,width,height') - using full frame")
        return None


def execute_zap_iterations(max_iteration: int, action: str = 'live_chup', goto_live: bool = True, audio_analysis: bool = False) -> bool:
    from shared.src.lib.executors.zap_executor import ZapExecutor

    device = get_device()
    context = get_context()
    args = get_args()

    motion_area = parse_motion_area(getattr(args, 'motion_area', ''))
    motion_threshold = max(0.0, float(getattr(args, 'motion_threshold', 1.0)))

    # ZapExecutor handles complete zap workflow
    zap_executor = ZapExecutor(device, context.userinterface,
                               motion_area=motion_area, motion_threshold=motion_threshold)
    return zap_executor.execute_zap_iterations(action, max_iteration, goto_live, audio_analysis)

@script("fullzap", "Execute zap iterations with analysis", default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()
    
    # Load navigation tree (required for ZapExecutor navigation)
    nav_result = device.navigation_executor.load_navigation_tree(
        context.userinterface, 
        context.team_id
    )
    if not nav_result['success']:
        context.error_message = f"Navigation tree loading failed: {nav_result.get('error', 'Unknown error')}"
        return False
    
    context.tree_id = nav_result['tree_id']
    
    success = execute_zap_iterations(
        max_iteration=args.max_iteration,
        action=args.action,
        goto_live=args.goto_live,
        audio_analysis=args.audio_analysis
    )
    
    # Print zap summary table and fullzap summary
    from shared.src.lib.utils.zap_utils import print_zap_summary_table

    context = get_context()
    # Set the real verdict BEFORE printing summaries. The @script decorator only
    # sets context.overall_success AFTER main() returns, so the summaries (which run
    # here, inside main) would otherwise always read the uninitialized default (False).
    context.overall_success = success
    print_zap_summary_table(context)  # This was removed - restored!
    print_fullzap_summary(context, context.userinterface)

    return success

# Script arguments (framework params have defaults, script params are specific)
main._script_args = [
    '--userinterface:str:example_mobile',  # Framework param with default
    '--variant:str:',                              # Optional named variant; empty = base
    '--max-iteration:int:3',
    '--action:str:live_chup',
    '--goto-live:bool:true',
    '--audio-analysis:bool:false',
    '--motion-area:str:',                          # Optional 'x,y,width,height'; default = centre 60% of frame
    '--motion-threshold:float:1.0'                 # Min frame-to-frame change % to count as motion
]
main._script_description = "Run channel zap iterations with analysis."
main._arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': "Optional variant name; if omitted, base data is used.",
    'max-iteration': 'Number of zap iterations',
    'action': 'Zap action to execute',
    'goto-live': 'Navigate to live before zapping',
    'audio-analysis': 'Enable audio analysis',
    'motion-area': "Optional 'x,y,width,height' for the post-zap motion check; defaults to the centre 60% of the frame (excludes header/footer/side overlays).",
    'motion-threshold': 'Minimum frame-to-frame change percentage to count the destination as playing. Lower it when valid content is nearly static; raise it to reject overlay-only movement.',
}
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()

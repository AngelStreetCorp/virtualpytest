#!/usr/bin/env python3
"""
Zap Digit - Direct Digit-Keypress Channel Zapping Test Script

Like zap_chup, but instead of executing a `live_chup` action node it enters channel
NUMBERS directly on the remote keypad. You give it channel pairs (e.g. "123>300") and
it ping-pongs source ↔ destination for the requested number of iterations, verifying
the destination is actually playing (real frame-to-frame motion) after every channel
entry.

DEVICE SCOPE — TV / STB only
----------------------------
Digit zapping needs a numeric keypad on the remote. That means TV/STB targets:
Android TV (ADB), IR STBs (ir_conf/*.json), and BLE STBs (ble_conf/arris.json).
Android PHONES have no digit keypad remote, so this script does not apply to
android_mobile — point it at a TV interface (default: example_tv).

KEY MAPPING — no mistakes by construction
-----------------------------------------
The user only ever types channel NUMBERS (0-9). Each digit char is mapped to the
device's real remote key via DIGIT_KEYMAP below (the universal STB convention
'KEY_0'..'KEY_9', present in every IR config and the BLE config, and added to the
Android TV ADB keymap). A non-digit in --zaps is rejected up front, so an invalid
remote key can never be sent.

This is driven from RunTests via plain parameters (text + numbers), so there is
nothing new to build in the frontend:
    zaps            123>300, 11>42   (text)   channel pairs, looped
    digit_wait_ms   400              (number)  pause after each digit
    final_wait_time 3000             (number)  pause after full channel (ms), before motion check
    iterations      1                (number)  source↔destination round trips per pair
    goto_live       true             (switch)  navigate to live first; turn off to re-run from live

Usage:
    python test_scripts/tv/zap_digit.py --zaps "123>300" --iterations 5
    python test_scripts/tv/zap_digit.py example_tv --zaps "123>300, 11>42"
"""

import sys
import os
import time

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.executors.zap_executor import ZapExecutor
from shared.src.lib.utils.device_utils import capture_screenshot_for_script

# Digit char -> remote key name passed to press_key(). 'KEY_0'..'KEY_9' is the
# convention shared by every IR config (ir_conf/*.json), the BLE config
# (ble_conf/arris.json), and the Android ADB keymap (adb_utils.ADB_KEYS). The user
# only types digits, so a key name can never be mistyped.
DIGIT_KEYMAP = {str(d): f'KEY_{d}' for d in range(10)}

# Script metadata — declared at MODULE TOP on purpose. The server's parameter
# analyzer (server_script_routes.py) only reads the first 300 lines of a script,
# and main()'s body is longer than that. These constants are attached to main()
# at the bottom of the file for the @script runtime. Keep them here so RunTests
# shows the parameters instead of "No parameters".
_script_args = [
    '--userinterface:str:example_tv',      # TV/STB interface (phones have no digit keypad)
    '--variant:str:',                      # Optional named variant; empty = base
    # Free-text name for THIS run, set at launch in RunTests. The digits zapped
    # change per run, so the name is dynamic (e.g. "HD sweep 123↔300"); empty
    # falls back to the zap pairs. Names the report (summary + step rows).
    '--display_name:str:',
    '--zaps:str:123>300',                  # Channel pairs 'src>dst', comma-separated; looped
    '--digit-wait-ms:int:400',             # Pause after each digit key
    '--final-wait-time:int:3000',          # Pause (ms) after full channel, before motion check
    '--iterations:int:1',                  # Source↔destination round trips per pair
    '--motion-threshold:float:1.0',        # Min frame-to-frame change % to count as motion
    '--motion-window-s:float:2.0',         # Seconds between the two compared frames (max 2.0)
    '--goto-live:bool:true',               # Navigate to live first; turn off to re-run from live
    '--live-node:str:live',                # Node label to navigate to when --goto-live is true
]
_script_description = "Zap between channel pairs by entering channel numbers directly on the keypad."
_arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': "Optional variant name; if omitted, base data is used.",
    'display_name': "Friendly name for this run (set at launch); defaults to the zap pairs if blank.",
    'zaps': "Channel pairs to ping-pong, e.g. '123>300, 11>42'. Each side must be digits only.",
    'digit-wait-ms': 'Milliseconds to wait after each digit key press',
    'final-wait-time': 'Milliseconds to wait after the full channel is entered, before checking motion',
    'iterations': 'Number of source↔destination round trips per pair',
    'motion-threshold': 'Minimum frame-to-frame change percentage to count the destination as playing. Lower it when valid content is nearly static; raise it to reject overlay-only movement.',
    'motion-window-s': 'Seconds between the two frames the motion check compares (capped at 2.0). A wider window gives slow/near-static content more chance to move, reducing false "not playing" misses.',
    'goto-live': 'Navigate to live first; turn off to re-run repeatedly from live',
    'live-node': 'Node label to navigate to when --goto-live is true',
}
_target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}


def parse_zaps(zaps_str: str):
    """Parse '123>300, 11>42' into [('123','300'), ('11','42')].

    Raises ValueError on anything that isn't `digits>digits` so a malformed channel
    (or a non-digit key) is rejected before any key is sent.
    """
    pairs = []
    for raw in (zaps_str or '').split(','):
        token = raw.strip()
        if not token:
            continue
        if '>' not in token:
            raise ValueError(f"'{token}' is not a 'source>destination' pair (use e.g. 123>300)")
        source, destination = [side.strip() for side in token.split('>', 1)]
        for label, channel in (('source', source), ('destination', destination)):
            if not channel:
                raise ValueError(f"'{token}' has an empty {label} channel")
            if not channel.isdigit():
                raise ValueError(f"{label} channel '{channel}' in '{token}' is not all digits (0-9)")
        pairs.append((source, destination))
    if not pairs:
        raise ValueError("no channel pairs found - expected e.g. '123>300, 11>42'")
    return pairs


@script("zap_digit", "Zap between channels by entering channel numbers directly (TV/STB only)", default_device="device1")
def main():
    """Ping-pong between channel pairs by typing channel numbers on the remote keypad."""
    args = get_args()
    context = get_context()
    device = get_device()

    iterations = int(args.iterations)
    digit_wait = max(0, int(args.digit_wait_ms)) / 1000.0
    final_wait = max(0, int(args.final_wait_time)) / 1000.0  # ms -> seconds

    # Validate channel pairs up front (no key is sent if this fails).
    try:
        pairs = parse_zaps(args.zaps)
    except ValueError as e:
        context.error_message = f"Invalid --zaps: {e}"
        return False

    # Friendly name for this run (set at launch in RunTests). The digits change
    # per run, so the name is dynamic; fall back to the pair list when blank.
    # `display_name` is the operator's explicit value — only it is stamped onto
    # the per-event zap report (the fallback pairs string would be redundant
    # there next to the channel). `run_name` (with fallback) names the SCRIPT
    # report.
    display_name = (args.display_name or '').strip()
    run_name = display_name or ', '.join(f'{s}→{d}' for s, d in pairs)

    print(f"\n{'='*60}")
    print(f"🔢 ZAP DIGIT - Direct Channel-Number Zapping")
    print(f"{'='*60}")
    print(f"🏷️  Run: {run_name}")
    print(f"📱 Device: {device.device_name} ({device.device_model})")
    print(f"🔁 Pairs: {', '.join(f'{s}→{d}' for s, d in pairs)}")
    print(f"🔄 Iterations per pair: {iterations}")
    print(f"⌨️  Digit wait: {digit_wait:.2f}s | Final wait: {final_wait:.2f}s")
    print(f"{'='*60}\n")

    # Remote controller for the direct key presses.
    remote_controller = device._get_controller('remote')
    if not remote_controller:
        context.error_message = "No 'remote' controller found on device"
        return False

    # Load navigation tree (needed for the optional goto-live, harmless otherwise).
    nav_result = device.navigation_executor.load_navigation_tree(
        context.userinterface,
        context.team_id
    )
    if not nav_result['success']:
        context.error_message = f"Navigation tree loading failed: {nav_result.get('error', 'Unknown error')}"
        return False
    context.tree_id = nav_result['tree_id']

    # Optionally navigate to live first so playback is active before we start zapping.
    if args.goto_live:
        import asyncio
        print(f"📍 Navigating to '{args.live_node}' before zapping...")
        nav = asyncio.run(device.navigation_executor.execute_navigation(
            tree_id=context.tree_id,
            userinterface_name=context.userinterface,
            target_node_label=args.live_node,
            team_id=context.team_id,
            context=context
        ))
        if not nav.get('success'):
            context.error_message = f"goto-live failed: {nav.get('error')}"
            return False

    # Reuse ZapExecutor's strict real motion detection (any frozen/blackscreen frame
    # ⇒ no motion) to verify the destination is actually playing after each entry.
    # motion_threshold tunes how much frame-to-frame change counts as "playing" — lower
    # it when valid content is nearly static (two close-but-different frames).
    motion_threshold = max(0.0, float(args.motion_threshold))
    # Seconds between the two frames the motion check compares. A wider window gives
    # slow/near-static live content more chance to move, cutting false "NOT DETECTED"
    # misses; the helper caps the real gap at 2.0s, so clamp here too.
    motion_window = min(2.0, max(0.0, float(args.motion_window_s)))
    print(f"🎚️  Motion threshold: {motion_threshold}% change | window: {motion_window:.1f}s")
    zap_executor = ZapExecutor(device, context.userinterface,
                               motion_threshold=motion_threshold, motion_duration=motion_window)

    def enter_channel(channel: str):
        """Type a channel number digit-by-digit; stamp last_action.json so vpt-monitor
        can attribute the upcoming zap to us. Returns (all_keys_ok, action_timestamp)."""
        keys = [DIGIT_KEYMAP[d] for d in channel]
        print(f"   ⌨️  Channel {channel}: [{' '.join(keys)}]")
        all_ok = True
        for d in channel:
            ok = remote_controller.press_key(DIGIT_KEYMAP[d])
            if not ok:
                print(f"      ❌ press_key('{DIGIT_KEYMAP[d]}') failed")
                all_ok = False
            if digit_wait > 0:
                time.sleep(digit_wait)
        # The channel commits on the last digit → the zap (blackscreen/freeze) starts
        # now. Record last_action.json AS THAT DIGIT'S KEY PRESS: capture_monitor's
        # zap-key gate only treats CHANNEL_UP/DOWN or a digit/KEY_n as a zap, so a
        # command like 'digit_zap_300' is rejected as "not a channel-change key" and
        # the freeze is never analysed. params['key'] = 'KEY_<last digit>' is what the
        # monitor reads (see capture_monitor _check_for_zapping_async is_zap_key).
        action_ts = time.time()
        last_key = DIGIT_KEYMAP[channel[-1]]
        # The run's display name rides in params: it flows intact through
        # last_action.json → vpt-monitor's action_info → zap_event['action_params']
        # → the zap report + zap_results.action_params (jsonb), so it appears on
        # the per-event zapping report with no monitor/DB change. Only stamped
        # when the operator set one (the fallback would be redundant on the report).
        action_params = {'key': last_key, 'channel': channel}
        if display_name:
            action_params['display_name'] = display_name
        try:
            from backend_host.src.lib.utils.frame_metadata_utils import write_action_to_frame_json
            write_action_to_frame_json(
                device, {'command': 'press_key', 'params': action_params}, action_ts
            )
        except Exception as e:
            print(f"      ⚠️ write_action_to_frame_json failed (zap measurement may miss): {e}")
        return all_ok, action_ts

    def capture_full_frame(label: str):
        """Capture a full (uncropped) source frame, add it to context, return its path."""
        try:
            sid = capture_screenshot_for_script(device, context, label)
            if sid and context.screenshot_paths:
                return context.screenshot_paths[-1]
        except Exception as e:
            print(f"⚠️ [zap_digit] full-frame capture '{label}' failed: {e}")
        return None

    def record_zap_step(channel: str, from_label: str, pressed_ok: bool, motion: dict,
                        success: bool, start_time: float, end_time: float,
                        start_full: str, end_full: str, measurement: dict = None,
                        non_blocking: bool = False):
        """Record one report step per channel entry (category 'zap_action').

        Images per step:
          - step_start = original full frame before zapping (left bookend)
          - step_end   = original full frame on the settled destination (right bookend)
          - the two cropped frames detect_real_motion compared render UNDER
            'Analysis Results → Motion Detection' (motion_analysis_images), not as separate
            'motion 1 / motion 2' Action rows — they belong to the motion check, not actions.
        All are already in context.screenshot_paths; the step only references them.

        Status badge: PASS (motion confirmed) / FAIL (a digit was rejected by the remote,
        or the destination's frame change stayed below the motion threshold)."""
        images = (motion or {}).get('images') or []
        change = (motion or {}).get('change')
        threshold = (motion or {}).get('threshold')
        area = (motion or {}).get('area')
        motion_ok = bool((motion or {}).get('motion'))

        if not pressed_ok:
            error = 'Key press failed (digit not accepted by remote)'
        elif not motion_ok:
            if non_blocking:
                # First entry of the run (warm-up): below-threshold motion is treated
                # as a non-blocking warning — the destination is playing but nearly
                # static (e.g. a paused sports scene), so no error is raised, the step
                # still passes, and the KPI measurement is kept.
                error = None
            # Channel entered but the two settled frames changed less than the threshold,
            # so playback could not be confirmed → a real failure.
            elif change is not None and threshold is not None:
                error = f'No motion detected: {change:.1f}% change < {threshold}% threshold'
            else:
                error = 'No motion detected (channel entered but destination not playing)'
        else:
            error = None

        message = f"Enter channel {channel}"
        if change is not None:
            message += f" — motion {change:.1f}%"
        if non_blocking and not motion_ok:
            message += " (first entry — not blocking)"

        # Motion check details — drives the 'Motion Detection: DETECTED / NOT DETECTED
        # (X% change / Y% threshold)' line and the compared-frame thumbnails.
        motion_analysis = {
            'success': motion_ok,
            'change_percentage': change,
            'real_motion_change': change,
            'real_motion_threshold': threshold,
            'real_motion_area': area,
        }
        if images:
            motion_analysis['motion_analysis_images'] = images

        step = {
            'success': success,
            'from_node': from_label,
            'to_node': f'ch {channel}',
            'step_category': 'zap_action',
            'execution_time_ms': int(max(0.0, end_time - start_time) * 1000),
            'start_time': time.strftime('%H:%M:%S', time.localtime(start_time)),
            'end_time': time.strftime('%H:%M:%S', time.localtime(end_time)),
            'motion_analysis': motion_analysis,
            'error': error,
            'message': message,
            'screenshots': [],  # frames already in context.screenshot_paths (don't double-add)
        }
        # Original full frames as the step start/end bookends.
        if start_full:
            step['step_start_screenshot_path'] = start_full
        if end_full:
            step['step_end_screenshot_path'] = end_full
            step['screenshot_path'] = end_full

        # Local zap measurement from vpt-monitor (channel + durations), if detected.
        # Renders under the step's "Analysis Results → Zap Detection".
        if measurement:
            step['zapping_analysis'] = {
                'success': True,
                'zapping_detected': True,
                'total_zap_duration_ms': measurement.get('total_zap_duration_ms') or 0,
                'blackscreen_duration_ms': measurement.get('blackscreen_duration_ms') or 0,
                'transition_type': 'freeze' if measurement.get('detection_type') == 'freeze' else 'blackscreen',
                # Link to this entry's standalone zap measurement report (rendered as a
                # "View Zap Report" link in the step's Zap Detection block).
                'report_url': measurement.get('report_url'),
                'channel_info': {
                    'channel_name': measurement.get('channel_name', ''),
                    'channel_number': measurement.get('channel_number', ''),
                    'program_name': measurement.get('program_name', ''),
                },
            }
        context.record_step_dict(step)

    def enter_and_verify(channel: str, from_label: str, first_entry: bool = False) -> dict:
        """Enter a channel, wait for it to settle, check it is actually playing, record a step.

        first_entry: the very first channel entry of the run is a warm-up — content can be
        nearly static (e.g. a paused sports scene) and score below the motion threshold even
        though the destination IS playing. A first-entry miss is recorded but treated as
        non-blocking (does not fail the run, keeps the KPI measurement). Key-press failures
        still block, and every later entry stays strict.
        """
        start_time = time.time()
        start_full = capture_full_frame(f"zap_{channel}_start")  # original frame before zapping
        pressed_ok, action_ts = enter_channel(channel)
        motion = None
        if pressed_ok:
            if final_wait > 0:
                time.sleep(final_wait)
            motion = zap_executor.detect_real_motion(context)
        end_full = capture_full_frame(f"zap_{channel}_end")  # original frame on settled destination
        end_time = time.time()  # zap work done; the measurement fetch below is best-effort bookkeeping

        # Best-effort: pull the local zap measurement vpt-monitor wrote for this action.
        measurement = zap_executor.fetch_zap_measurement(context, action_ts) if pressed_ok else None
        # Remember the latest per-event zap report URL for the summary header link
        # (each entry also links its own report on its step). Last one wins → most recent zap.
        if measurement and measurement.get('report_url'):
            if getattr(context, 'custom_data', None) is None:
                context.custom_data = {}
            context.custom_data['zap_report_url'] = measurement['report_url']

        # detect_real_motion returns its result dict whether or not motion was found
        # (the dict carries the change% and compared frames even on a miss), so the
        # verdict is motion['motion'], NOT the truthiness of the dict.
        motion_detected = bool(motion and motion.get('motion'))
        played = pressed_ok and motion_detected
        # First entry of the run with keys OK but no motion → non-blocking warm-up miss.
        non_blocking = first_entry and pressed_ok and not motion_detected
        step_pass = played or non_blocking  # report step badge (⚠️ PASS on a non-blocking miss)
        if motion_detected:
            motion_label = '✅ DETECTED'
        elif non_blocking:
            motion_label = '⚠️ NOT DETECTED (first entry — not blocking)'
        else:
            motion_label = '❌ NOT DETECTED'
        print(f"      📊 ch {channel}: keys {'✅' if pressed_ok else '❌'} | motion {motion_label}")
        if measurement:
            total_ms = measurement.get('total_zap_duration_ms')
            ch = measurement.get('channel_number') or '?'
            name = measurement.get('channel_name', '')
            duration_str = f" | total {total_ms}ms" if total_ms else ""
            print(f"      📺 zap measured: ch {ch} {name}{duration_str}")
        record_zap_step(channel, from_label, pressed_ok, motion, step_pass,
                        start_time, end_time, start_full, end_full, measurement,
                        non_blocking=non_blocking)
        return {
            'channel': channel,
            'success': played,        # real "played" verdict (motion confirmed)
            'non_blocking': non_blocking,
            'pressed_ok': pressed_ok,
            'motion_detected': motion_detected,
            'measurement': measurement,
        }

    # ============================================
    # EXECUTE
    # ============================================
    results = []  # one entry per channel entry (2 per iteration)
    from_label = args.live_node if args.goto_live else 'live'
    for source, destination in pairs:
        pair_name = f"{source}→{destination}"
        print(f"\n{'='*60}")
        print(f"🔁 PAIR {pair_name}  ({iterations} iteration(s))")
        print(f"{'='*60}")

        for i in range(iterations):
            iteration_num = i + 1
            print(f"\n📍 Iteration {iteration_num}/{iterations} — {pair_name}")

            for leg, channel in (('source', source), ('destination', destination)):
                first_entry = (len(results) == 0)  # very first channel entry of the run (warm-up)
                r = enter_and_verify(channel, from_label, first_entry=first_entry)
                from_label = f'ch {channel}'  # next step zaps FROM this channel
                r.update({'pair': pair_name, 'iteration': iteration_num, 'leg': leg})
                results.append(r)
                # Only a BLOCKING failure sets the run error. The first entry's
                # near-static motion miss is non-blocking (destination playing, just
                # static), so it must not fail the run — key-press failures still do.
                if not r['success'] and not r.get('non_blocking'):
                    context.error_message = (
                        f"[{pair_name}] iteration {iteration_num} {leg} (ch {channel}) failed "
                        f"({'key press' if not r['pressed_ok'] else 'frozen / no motion'})"
                    )

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

    successful = sum(1 for r in results if r['success'])
    non_blocking_count = sum(1 for r in results if r.get('non_blocking'))
    # Blocking failures = entries that didn't play AND aren't the non-blocking first-entry miss.
    blocking_failures = sum(1 for r in results if not r['success'] and not r.get('non_blocking'))
    # "Frozen" = genuinely frozen blocking entries (the non-blocking first-entry miss is
    # reported separately so it isn't double-counted here).
    frozen_count = sum(1 for r in results
                       if r['pressed_ok'] and not r['motion_detected'] and not r.get('non_blocking'))
    key_fail_count = sum(1 for r in results if not r['pressed_ok'])
    measured_count = sum(1 for r in results if r.get('measurement'))

    print(f"\n{'='*60}")
    print(f"🎯 ZAP DIGIT SUMMARY")
    print(f"{'='*60}")
    print(f"   🏷️ Display name: {run_name}")
    print(f"   📋 Interface: {args.userinterface}")
    print(f"   🎭 Variant: {variant or 'base'}")
    print(f"\n   📊 Results by channel entry:")
    for r in results:
        status = "✅" if r['success'] else ("⚠️" if r.get('non_blocking') else "❌")
        keys = "keys✅" if r['pressed_ok'] else "keys❌"
        motion = "motion✅" if r['motion_detected'] else "motion❌"
        meas = r.get('measurement')
        meas_str = ""
        if meas:
            total_ms = meas.get('total_zap_duration_ms')
            meas_str = f"  📺 {meas.get('channel_number') or '?'} {meas.get('channel_name', '')}"
            if total_ms:
                meas_str += f" ({total_ms}ms)"
        print(f"      {status} [{keys} {motion}] {r['pair']} #{r['iteration']} {r['leg']} (ch {r['channel']}){meas_str}")

    print(f"\n   📈 Statistics:")
    print(f"      Total channel entries: {len(results)}")
    print(f"      Played (motion confirmed): {successful}")
    print(f"      Blocking failures: {blocking_failures}")
    if non_blocking_count:
        print(f"      Non-blocking first-entry misses: {non_blocking_count}")
    print(f"      Frozen destination (keys sent but no motion): {frozen_count}")
    print(f"      Key-press failures: {key_fail_count}")
    print(f"      Zap measurements fetched: {measured_count}/{len(results)}")
    print(f"{'='*60}\n")

    # Success = at least one entry actually played AND no blocking failures. The first
    # entry's near-static motion miss is non-blocking (warm-up), so it doesn't fail the
    # run — but a key-press failure or any later frozen entry does.
    context.overall_success = (successful >= 1) and (blocking_failures == 0)
    # execution_summary is what the HTML report renders (the print() block above
    # is log-only). Lead with the display name so the run is identifiable in the
    # report's "Execution Summary" section.
    nb_note = f", {non_blocking_count} non-blocking first-entry" if non_blocking_count else ""
    context.execution_summary = (
        f"🏷️ Display name: {run_name}\n"
        f"📋 Interface: {args.userinterface}  |  🎭 Variant: {variant or 'base'}\n"
        f"Zap digit: {successful}/{len(results)} entries played, "
        f"{frozen_count} frozen{nb_note}, {key_fail_count} key-press failures"
    )
    return context.overall_success


# Attach the module-top metadata to main() for the @script runtime.
# (The literals live at the top of the file so the server's 300-line parameter
# analyzer can see them — see the comment next to their definitions.)
main._script_args = _script_args
main._script_description = _script_description
main._arg_descriptions = _arg_descriptions
main._target_rules = _target_rules

if __name__ == "__main__":
    main()

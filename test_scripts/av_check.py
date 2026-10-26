#!/usr/bin/env python3
"""
AV Check - is this device playing audio and video?

Navigates to a node that plays sound (a YouTube video on web / mobile, live TV on an
STB, the stream itself on an HLS device), watches it for `--duration` seconds and
gives two verdicts:

  * VIDEO - the picture is moving (real frame-to-frame motion above
    `--motion-threshold`) and no freeze / black window lasts longer than
    `--max-freeze-s`.
  * AUDIO - sound is present for at least `--audio-min-present` % of the window.

The report carries the evidence: the two frames the motion check compared (with the
measured change %, fullzap style), a screenshot at the start / middle / end of the
window, a table with the audio level (dB) of every second, the silence windows and
the freeze / black windows. The executive summary stays short - it is the verdict;
the numbers are in the table of the step.

**The sound is put up before the watch.** A device that is muted, or whose volume
is at 0, is silent without being broken, so the check asks the device what it can
tell it (a browser player says whether it is muted) and raises the volume to the
maximum. The script never presses MUTE: muting the device to make the check fail
would be the script creating the failure it then reports. When the device cannot
say whether it is muted (a set-top box shows no mute icon on the picture), the
report says exactly that instead of guessing.

Nothing here re-implements detection. Every verdict comes from the platform's own
code:

  * navigation                 NavigationExecutor.execute_navigation (the same call
                               goto.py makes)
  * per-second audio / freeze / blackscreen
                               backend_host.src.lib.utils.analysis_utils
                               .load_recent_analysis_data_from_path - the capture
                               monitor's per-frame JSON, the same source the
                               DetectMotionFromJson verification reads. The monitor
                               also writes the pixel difference it measured against
                               the previous frames (`freeze_diffs`) and its own
                               verdict on it (`freeze`), so "did the picture move"
                               is read from the platform, never recomputed here
  * motion between frames      ZapExecutor.detect_real_motion -> the DetectMotion
                               video verification -> video_analysis_helpers
                               .compare_images_for_motion
  * screenshots                device_utils.capture_screenshot_for_script

Usage:
    python test_scripts/av_check.py [--userinterface <name>] [--node <node>]
                                    [--duration <seconds>] [--device <device_id>]

Examples:
    python test_scripts/av_check.py --userinterface example_mobile --node live
    python test_scripts/av_check.py --userinterface youtube-web --node video_player --duration 30
    python test_scripts/av_check.py --node live --motion-threshold 0.5 --audio-min-present 80
"""

import sys
import os
import time

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device

# Script arguments - declared at module top because the backend param analyzer
# only reads the first 300 lines of the file. Bound to main() at the bottom.
_script_args = [
    '--userinterface:str:example_mobile',   # Framework param with default
    '--variant:str:',                       # Optional named variant; empty = base
    '--node:str:home',                      # Node that plays content with sound
    '--duration:int:30',                    # Seconds to watch
    '--settle-s:float:3.0',                 # Settle time after navigation
    '--motion-threshold:float:1.0',         # Min frame-to-frame change % to count as motion
    '--motion-window-s:float:2.0',          # Seconds between the two compared frames (max 2.0)
    '--motion-area:str:',                   # Optional "x,y,width,height" region
    '--audio-min-present:float:60.0',       # Min % of the window that must have audio
    '--audio-level-db:float:-50.0',         # mean_volume_db floor for "audio present"
    '--prepare-audio:bool:true',            # Put the sound up before watching (never mute)
    '--volume-presses:int:20',              # VOLUME_UP presses that reach the maximum volume
    '--max-freeze-s:float:5.0',             # Longest tolerated freeze / black window
    '--no-navigate:bool:false',             # Watch the current screen instead of navigating
    '--verify:str:end:end|each|auto',       # Verification mode dropdown
]

# The platform's own "sound is playing" floor (backend_host/scripts/monitor_localize.py,
# AUDIO_PLAYING_DB). A second only counts as audible when the monitor says audio is
# present AND the level is above this.
DEFAULT_AUDIO_LEVEL_DB = -50.0


def parse_motion_area(raw):
    """'x,y,width,height' -> the {x, y, width, height} dict the motion helpers take.

    Returns None for an empty / malformed value so the helper falls back to its
    default centred region (same as the zap flow with no --motion-area).
    """
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).replace(' ', ',').split(',') if p.strip()]
    if len(parts) != 4:
        return None
    try:
        x, y, w, h = (int(float(p)) for p in parts)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {'x': x, 'y': y, 'width': w, 'height': h}


def load_window_frames(device, window_start, window_end):
    """The capture monitor's per-frame analysis for the watch window.

    Reuses backend_host.src.lib.utils.analysis_utils.load_recent_analysis_data_from_path
    - the loader the DetectMotionFromJson verification and the zap flow use - and keeps
    only the frames written inside the window.

    Returns (frames, error). frames is a list of {file_mtime, analysis_json} oldest first.
    """
    try:
        from backend_host.src.lib.utils.analysis_utils import load_recent_analysis_data_from_path
    except Exception as e:  # noqa: BLE001 - the host may not have backend_host on the path
        return [], f'Capture analysis is not available here: {e}'

    av_controller = device._get_controller('av') if device else None
    capture_path = getattr(av_controller, 'video_capture_path', None) if av_controller else None
    if not capture_path:
        return [], 'This device has no AV controller, so there is nothing to analyse'

    result = load_recent_analysis_data_from_path(capture_path, timeframe_minutes=5, max_count=None)
    if not result.get('success'):
        return [], result.get('error') or 'Could not read the capture analysis'

    start_ms = window_start * 1000
    end_ms = window_end * 1000
    frames = []
    for item in result.get('analysis_data') or []:
        mtime = item.get('file_mtime') or 0
        if start_ms <= mtime <= end_ms:
            frames.append(item)
    frames.sort(key=lambda i: i.get('file_mtime') or 0)
    return frames, None


def can_navigate(device):
    """True when the device has a controller that can drive its UI.

    A stream device (HLS / RTSP box) has no remote, browser or desktop: it plays
    what it plays and there is nothing to navigate. The check then watches the
    current screen instead of failing on a key press that cannot happen.
    """
    if device is None:
        return False
    for controller_type in ('remote', 'web', 'desktop'):
        try:
            if device.has_controller(controller_type):
                return True
        except Exception:  # noqa: BLE001 - an unknown device shape must not break the run
            continue
    return False


# ---------------------------------------------------------------------------
# The sound: is the device muted, and is the volume up?
# ---------------------------------------------------------------------------
# A device that is muted, or whose volume is at 0, is silent without being
# broken. So the check asks the device what it can tell us and puts the volume
# up before it watches. What the script NEVER does is press MUTE: muting the
# device to make the check fail would be the script creating the failure it
# then reports.


def read_mute_state(device):
    """Is the device muted? True / False, or None when the device cannot say.

    A browser can tell us: the page's media element carries a `muted` flag (a
    video that autoplays muted is silent while everything is fine). A set-top
    box with a remote cannot - it shows no mute icon and no volume bar on the
    picture - so the answer there is None, and the report says so instead of
    guessing.
    """
    if device is None:
        return None
    try:
        if not device.has_controller('web'):
            return None
        web_controller = device._get_controller('web')
        if web_controller is None:
            return None
    except Exception:  # noqa: BLE001 - an unknown device shape must not break the run
        return None

    try:
        import asyncio
        from shared.src.lib.utils.local_debug_playwright_js import WEB_JS_AUDIO_STATE
        result = asyncio.run(web_controller.execute_javascript(WEB_JS_AUDIO_STATE))
    except Exception:  # noqa: BLE001 - no page, no JS, no answer
        return None
    if not isinstance(result, dict) or not result.get('found'):
        return None
    muted = result.get('muted')
    return bool(muted) if isinstance(muted, bool) else None


def clear_mute(device):
    """Clear a mute the device reports itself. True when the device is unmuted after this.

    Only a browser can do this: the platform's own "make sure the player is
    not muted" script, the one the Facebook check uses.
    """
    if device is None:
        return False
    try:
        if not device.has_controller('web'):
            return False
        web_controller = device._get_controller('web')
        if web_controller is None:
            return False
    except Exception:  # noqa: BLE001 - an unknown device shape must not break the run
        return False

    try:
        import asyncio
        from shared.src.lib.utils.local_debug_playwright_js import WEB_JS_ENSURE_UNMUTED
        result = asyncio.run(web_controller.execute_javascript(WEB_JS_ENSURE_UNMUTED))
    except Exception:  # noqa: BLE001 - no page, no JS, no answer
        return False
    return bool(isinstance(result, dict) and result.get('success'))


def raise_volume(device, presses):
    """Press VOLUME_UP `presses` times so the volume sits at the maximum.

    A volume at 0 is a reason for silence that has nothing to do with the
    device, and on most boxes VOLUME_UP also clears a mute. Returns the number
    of presses the device accepted.
    """
    if device is None or presses <= 0:
        return 0
    try:
        if not device.has_controller('remote'):
            return 0
        remote = device._get_controller('remote')
        if remote is None:
            return 0
    except Exception:  # noqa: BLE001 - an unknown device shape must not break the run
        return 0

    accepted = 0
    for _ in range(presses):
        try:
            if remote.press_key('VOLUME_UP'):
                accepted += 1
        except Exception:  # noqa: BLE001 - a key the remote does not know
            break
        time.sleep(0.15)
    return accepted


def prepare_audio(device, presses):
    """Make sure the device is able to play sound, and say what was done.

    Returns a dict with:
      * `muted`     - True / False when the device told us, None when it cannot say;
      * `unmuted`   - True when a mute we could see was cleared;
      * `volume`    - the number of VOLUME_UP presses the device accepted;
      * `source`    - 'player' when the device is a browser, 'remote' when it has
                      a remote, '' when it has neither.
    """
    state = {'muted': None, 'unmuted': False, 'volume': 0, 'source': ''}
    if device is None:
        return state

    muted = read_mute_state(device)
    state['muted'] = muted
    if muted:
        state['unmuted'] = clear_mute(device)
        state['source'] = 'player'

    volume = raise_volume(device, presses)
    if volume:
        state['volume'] = volume
        if not state['source']:
            state['source'] = 'remote'
    return state


def sound_label(state):
    """One line for the report: the mute state of the device.

    Four cases, one line each, so the report can translate every one of them:
    a browser tells us whether its player is muted, a set-top box with a remote
    does not (it shows no mute icon on the picture), and the report says so
    instead of guessing.
    """
    if state.get('muted') is True:
        if state.get('unmuted'):
            return 'the player was muted and was unmuted before the check'
        return 'the device is muted'
    if state.get('muted') is False:
        return 'the device is not muted'
    return 'this device does not report a mute state'


def volume_label(state):
    """One line for the report: what was done with the volume (empty when nothing)."""
    if state.get('volume'):
        return f'raised to the maximum ({state["volume"]} x VOLUME_UP)'
    return ''


def audio_reason(state, min_present):
    """Why the audio verdict failed, in the words the report can translate.

    The reason names the cause the check actually knows: a device that is
    muted is not a device with a broken speaker, and a device whose mute state
    cannot be read is not a device that was proved to be silent by mistake.
    """
    if state.get('muted') is True and not state.get('unmuted'):
        return 'audio: the device is muted'
    if state.get('muted') is False:
        return (f'audio: present for less than {min_present}% of the window '
                f'(the device is not muted)')
    if state.get('volume'):
        return (f'audio: present for less than {min_present}% of the window '
                f'(the volume was raised to the maximum, the mute state is unknown)')
    return f'audio: present for less than {min_present}% of the window'



def frame_change_verdict(data):
    """What the capture monitor's own per-frame analysis says about this frame.

    Returns True when the picture moved, False when it stood still, and None when
    the monitor did not measure the frame.

    The monitor compares every frame with the previous ones and writes the pixel
    difference it measured in `freeze_diffs`; its own verdict `freeze` is True when
    none of those differences reached the platform's threshold
    (`backend_host/scripts/detector.py`, FREEZE_THRESHOLD). The platform's verdict
    plus its own numbers therefore already answer "did the picture move" - no image
    is compared here.

    A frame with no signal or a black screen has no picture to compare: it counts as
    "did not move" so it can never pass for motion.
    """
    diffs = data.get('freeze_diffs')
    if not isinstance(diffs, (list, tuple)):
        return None
    if not [d for d in diffs if isinstance(d, (int, float))]:
        return None
    freeze = data.get('freeze')
    if not isinstance(freeze, bool):
        return None
    if data.get('no_signal') or data.get('blackscreen'):
        return False
    return freeze is False


def bucket_per_second(frames, window_start):
    """One row per second of the window: audio state, level, freeze, blackscreen.

    The monitor snapshots the audio service's reading into every frame, so a second
    keeps the last known audio value it saw (None = the device captures no audio).

    **Freeze and motion are decided on the picture, not on the frame.** The monitor's
    per-frame `freeze` flag answers "was this frame identical to the one before it",
    which is a statement about the capture pipeline, not about the content: a grabber
    that delivers the same picture for several frames in a row (a phone on a slow HDMI
    mirror does exactly that) is flagged as frozen on every repeat even while a video
    is playing. So the freeze / motion verdict for a second is built from what the
    platform *measured* - its per-frame pixel difference and its verdict on it:

      * the second MOVED  when at least one of its frames saw a change;
      * the second stood still when every one of its frames was measured and none of
        them saw a change.

    A freeze window is then the *gap* between two of those moments - see
    `find_freeze_gaps`, which is where the verdict is made.

    A pipeline that writes no per-frame difference at all (an older or lighter
    capture) falls back to the flags it does write: the monitor's own `motion`
    verdict, then the `freeze` flag, both on the same majority rule the platform's
    `analysis_utils.get_motion_analysis` uses.
    """
    buckets = {}
    for item in frames:
        mtime = item.get('file_mtime') or 0
        second = int((mtime - window_start * 1000) // 1000)
        data = item.get('analysis_json') or {}
        row = buckets.setdefault(second, {
            'second': second,
            'audio': None,
            'audio_known': False,
            'mean_volume_db': None,
            'volume_percentage': None,
            'freeze': False,
            'blackscreen': False,
            'no_signal': False,
            'frames': 0,
            'freeze_frames': 0,
            'blackscreen_frames': 0,
            'no_signal_frames': 0,
            'motion': False,
            'motion_known': False,
            'motion_frames': 0,
            'motion_pct': None,
            'changed': False,
            'changed_frames': 0,
            'still_frames': 0,
            'unmeasured_frames': 0,
        })
        row['frames'] += 1
        audio = data.get('audio', None)
        if audio is not None:
            row['audio'] = audio
            row['audio_known'] = True
            level = data.get('mean_volume_db')
            if isinstance(level, (int, float)):
                row['mean_volume_db'] = float(level)
            volume = data.get('volume_percentage')
            if isinstance(volume, (int, float)):
                row['volume_percentage'] = float(volume)
        if data.get('freeze'):
            row['freeze_frames'] += 1
        if data.get('blackscreen'):
            row['blackscreen_frames'] += 1
        if data.get('no_signal'):
            row['no_signal_frames'] += 1
        # Did the picture move in this frame? The platform's own measurement.
        changed = frame_change_verdict(data)
        if changed is True:
            row['changed_frames'] += 1
        elif changed is False:
            row['still_frames'] += 1
        else:
            row['unmeasured_frames'] += 1
        # The monitor's own per-frame motion verdict ('static' = this frame did not
        # move, 'full' / 'box' / 'band' / 'minor' = it did). Kept as the fallback for
        # capture data that carries no pixel difference.
        motion = data.get('motion') or {}
        kind = motion.get('kind')
        if kind is not None:
            row['motion_known'] = True
            if kind != 'static':
                row['motion_frames'] += 1
            pct = motion.get('pct')
            if isinstance(pct, (int, float)):
                if row['motion_pct'] is None or pct > row['motion_pct']:
                    row['motion_pct'] = float(pct)

    for row in buckets.values():
        frames = row['frames']
        # Majority: more than half the frames carry the flag.
        row['blackscreen'] = row['blackscreen_frames'] * 2 > frames
        row['no_signal'] = row['no_signal_frames'] * 2 > frames
        measured = row['changed_frames'] + row['still_frames']
        # A second that is black or has no signal is not a freeze: it is reported
        # as black / no signal, which is the more useful answer.
        not_a_picture = row['blackscreen'] or row['no_signal']
        if measured:
            # The platform measured this second frame by frame.
            row['motion'] = row['changed_frames'] > 0
            row['changed'] = row['motion']
            # Frozen = the picture did not change at all during the second. A second
            # with an unmeasured frame is not frozen: we cannot say the picture stood
            # still over a stretch we did not look at.
            row['freeze'] = (row['changed_frames'] == 0
                             and row['unmeasured_frames'] == 0
                             and not not_a_picture)
            row['measured'] = True
        elif row['motion_known']:
            # No pixel difference, but the monitor wrote its own motion verdict.
            row['motion'] = row['motion_frames'] * 2 > frames
            row['changed'] = row['motion']
            row['freeze'] = row['freeze_frames'] * 2 > frames and not not_a_picture
            row['measured'] = False
        else:
            # Nothing but the freeze flag: the same majority rule.
            row['freeze'] = row['freeze_frames'] * 2 > frames and not not_a_picture
            row['motion'] = row['motion_frames'] * 2 > frames
            row['changed'] = not row['freeze']
            row['measured'] = False
    return [buckets[key] for key in sorted(buckets)]


def find_windows(rows, flag):
    """Contiguous runs of seconds where `flag` was seen -> [(start_second, length)]."""
    windows = []
    run_start = None
    for row in rows:
        if row.get(flag):
            if run_start is None:
                run_start = row['second']
        else:
            if run_start is not None:
                windows.append((run_start, row['second'] - run_start))
                run_start = None
    if run_start is not None:
        windows.append((run_start, rows[-1]['second'] - run_start + 1))
    return windows


def find_freeze_gaps(rows, max_freeze_s):
    """The stretches in which the picture never changed -> [(start_second, length)].

    The platform measures a change in the frame right after the picture moved (it
    compares a frame with the ones before it), so the seconds it reports are the
    moments the picture was alive. A freeze is therefore the **gap** between two of
    those moments - or between one of them and the edge of the watch window - and
    only a gap longer than the tolerance counts.

    Reading a freeze as a gap is what makes the verdict right on a pipeline whose
    picture updates slowly. A device that shows a new picture every other second is
    alive the whole time, while counting "the seconds without a change" would call
    that same device frozen. The opposite stays true as well: a picture that stops
    moving leaves a gap as wide as the time it stood still.
    """
    if not rows:
        return []
    first = rows[0]['second']
    last = rows[-1]['second']
    changed = [row['second'] for row in rows if row.get('changed')]
    if not changed:
        # The picture never changed in the window.
        return [(first, last - first + 1)]
    windows = []
    lead = changed[0] - first
    if lead > max_freeze_s:
        windows.append((first, lead))
    for before, after in zip(changed, changed[1:]):
        gap = after - before - 1          # the seconds between the two changes
        if gap > max_freeze_s:
            windows.append((before + 1, gap))
    tail = last - changed[-1]
    if tail > max_freeze_s:
        windows.append((changed[-1] + 1, tail))
    return windows


def frozen_seconds(windows):
    """The seconds covered by the freeze windows."""
    covered = set()
    for start, length in windows:
        covered.update(range(start, start + max(length, 1)))
    return covered


def second_has_audio(row, level_floor):
    """True when this second really carried sound.

    The monitor's `audio` flag is the audio service's own speech/level verdict; the
    level floor rejects a second flagged present but measured below the floor.
    """
    if row.get('audio') is not True:
        return False
    level = row.get('mean_volume_db')
    if level is None:
        return True
    return level >= level_floor


def format_windows(windows):
    """[(start, length)] -> 's3-5 (3s), s12 (1s)' for the report."""
    if not windows:
        return 'none'
    parts = []
    for start, length in windows:
        end = start + max(length, 1) - 1
        parts.append(f's{start}-{end} ({length}s)' if end > start else f's{start} ({length}s)')
    return ', '.join(parts)


def build_summary(context, args, device, node_name, rows, verdict):
    """The executive summary: the verdict, one translatable line per row.

    The per-second evidence is NOT here. It is the table that belongs to the
    step (see `build_audio_table`): a summary that carries the level of every
    second cannot be read at a glance, and it is the verdict that matters.
    """
    lines = []
    lines.append('🎯 [AV_CHECK] EXECUTION SUMMARY')
    if device is not None:
        lines.append(f'📱 Device: {device.device_name} ({device.device_model})')
    else:
        lines.append('📱 Device: Setup failed - no device selected')
    if context.host:
        lines.append(f'🖥️ Host: {context.host.host_name}')
    else:
        lines.append('🖥️ Host: Setup failed - no host available')
    lines.append(f'📋 Interface: {args.userinterface}')
    lines.append(f'🎭 Variant: {verdict["variant"] or "base"}')
    lines.append(f'🗺️ Target: {node_name}')
    lines.append(f'🧭 Navigation: {verdict["navigation_label"]}')
    lines.append(f'⏱️ Watched: {verdict["watched_s"]}s ({verdict["sampled_s"]} sampled seconds)')
    lines.append(f'📺 Video: {verdict["video_label"]}')
    lines.append(f'🔊 Audio: {verdict["audio_label"]}')
    lines.append(f'🔈 Sound: {verdict["sound_label"]}')
    if verdict.get('volume_label'):
        lines.append(f'🔉 Volume: {verdict["volume_label"]}')
    lines.append(f'🔇 Silence windows: {verdict["silence_label"]}')
    lines.append(f'🖼️ Freeze/black windows: {verdict["freeze_label"]}')
    lines.append(f'📈 Motion present: {verdict["motion_pct"]}')
    lines.append(f'📸 Screenshots: {len(context.screenshot_paths)} captured')
    lines.append(f'🎯 Result: {"SUCCESS" if context.overall_success else "FAILED"}')
    if context.error_message:
        lines.append(f'❌ Error: {context.error_message}')
    return '\n'.join(lines)


def build_audio_table(rows, verdict):
    """The audio level of every second of the window, as a table for the report.

    The table is the evidence behind the audio verdict: the level the capture
    measured, and whether that second really carried sound. It belongs to the
    step, not to the executive summary.
    """
    table_rows = []
    for row in rows:
        level = row.get('mean_volume_db')
        level_txt = f'{level:.1f} dB' if isinstance(level, (int, float)) else 'N/A'
        if not row.get('audio_known'):
            state = 'unknown'
        elif second_has_audio(row, verdict['audio_floor']):
            state = 'audio present'
        else:
            state = 'silent'
        table_rows.append([f"s{row['second']}", level_txt, state])
    return {'headers': ['Second', 'Level', 'Sound'], 'rows': table_rows}



@script('av_check', 'Check that a device is playing audio and video', default_device='device1')
def main():
    """Watch the device for `--duration` seconds and judge video + audio."""
    args = get_args()
    context = get_context()
    device = get_device()

    duration = max(1, int(args.duration))
    settle_s = max(0.0, float(args.settle_s))
    motion_threshold = max(0.0, float(args.motion_threshold))
    motion_window = min(2.0, max(0.0, float(args.motion_window_s)))
    motion_area = parse_motion_area(args.motion_area)
    audio_min_present = max(0.0, min(100.0, float(args.audio_min_present)))
    audio_floor = float(args.audio_level_db)
    max_freeze_s = max(0.0, float(args.max_freeze_s))
    prepare_audio_on = bool(getattr(args, 'prepare_audio', True))
    volume_presses = max(0, int(getattr(args, 'volume_presses', 20)))

    print(f'🎯 [av_check] Target node: {args.node}')
    print(f'⏱️  [av_check] Watching {duration}s (threshold {motion_threshold}%, audio min {audio_min_present}%)')
    if device is not None:
        print(f'📱 [av_check] Device: {device.device_name} ({device.device_model})')

    # Active variant for this run (device.navigation_context is canonical, args is the
    # fallback) - same resolution goto.py does.
    variant = None
    if device is not None and getattr(device, 'navigation_context', None):
        variant = device.navigation_context.get('variant')
    if not variant:
        variant = getattr(args, 'variant', None)
    if isinstance(variant, str):
        variant = variant.strip() or None

    rows = []
    verdict = {
        'variant': variant,
        'watched_s': duration,
        'sampled_s': 0,
        'video_label': 'not run',
        'audio_label': 'not run',
        'sound_label': 'not run',
        'volume_label': '',
        'silence_label': 'none',
        'freeze_label': 'none',
        'motion_pct': '0.0',
        'navigation_label': 'not run',
        'audio_floor': audio_floor,
    }
    node_name = args.node
    already_at_destination = False
    navigate = not getattr(args, 'no_navigate', False) and can_navigate(device)

    try:
        # ---- navigate to the node that plays sound -------------------------------
        if navigate:
            nav_result = device.navigation_executor.load_navigation_tree(
                args.userinterface,
                context.team_id
            )
            if not nav_result['success']:
                context.error_message = f'Navigation tree loading failed: {nav_result.get("error", "Unknown error")}'
                context.overall_success = False
                return False
            context.tree_id = nav_result['tree_id']

            import asyncio
            result = asyncio.run(device.navigation_executor.execute_navigation(
                tree_id=context.tree_id,
                userinterface_name=context.userinterface,
                target_node_label=args.node,
                team_id=context.team_id,
                context=context,
            ))

            if not result.get('success', False):
                context.error_message = result.get('error') or 'Navigation failed'
                context.overall_success = False
                return False

            already_at_destination = (len(context.step_results) == 0)
            verdict['navigation_label'] = (
                'already at the target - no navigation needed' if already_at_destination
                else 'navigated to the target')

            # The node's friendly display name (data.display_name), same resolver
            # standby_measurement / zap_chup use.
            try:
                from shared.src.lib.database.navigation_trees_db import get_node_display_name
                node_display = get_node_display_name(context.tree_id, context.team_id, args.node)
                if node_display:
                    node_name = node_display
            except Exception:  # noqa: BLE001 - the label is cosmetic
                node_display = None
        else:
            # No remote / browser / desktop: the device plays what it plays (an HLS
            # or RTSP box has no UI to drive). Watch the screen it is showing.
            reason = ('--no-navigate was set' if getattr(args, 'no_navigate', False)
                      else 'the device has no navigation controller')
            print(f'⏭️  [av_check] Skipping navigation ({reason}) - watching the current screen')
            node_name = 'current screen'
            verdict['navigation_label'] = f'skipped - {reason}'
            context.record_step_dict({
                'success': True,
                'step_category': 'av_check',
                'message': f'Navigation skipped: {reason}',
            })

        # ---- make sure the device can play sound, then watch ----------------------
        # The sound is put up BEFORE the watch window: a device that is muted or
        # whose volume is at 0 is silent without being broken, and the check
        # must not be the reason it is silent. MUTE is never pressed - the
        # script does not create the failure it reports.
        sound_state = {'muted': None, 'unmuted': False, 'volume': 0, 'source': ''}
        if prepare_audio_on and device is not None:
            print('🔈 [av_check] Preparing the sound (mute state, volume)')
            sound_state = prepare_audio(device, volume_presses)
            print(f'🔈 [av_check] Sound: {sound_label(sound_state)}')
        verdict['sound_label'] = sound_label(sound_state)
        verdict['volume_label'] = volume_label(sound_state)

        if settle_s:
            print(f'⏳ [av_check] Settling {settle_s}s before the watch window')
            time.sleep(settle_s)

        from shared.src.lib.utils.device_utils import capture_screenshot_for_script

        window_start = time.time()
        start_shot = capture_screenshot_for_script(device, context, 'av_check_start')
        print(f'📸 [av_check] Start screenshot: {start_shot or "none"}')

        mid_shot = None
        mid_at = window_start + duration / 2.0
        window_end = window_start + duration
        while True:
            now = time.time()
            if now >= window_end:
                break
            if mid_shot is None and now >= mid_at:
                mid_shot = capture_screenshot_for_script(device, context, 'av_check_middle')
                print(f'📸 [av_check] Middle screenshot: {mid_shot or "none"}')
            time.sleep(0.25)
        window_end = time.time()
        end_shot = capture_screenshot_for_script(device, context, 'av_check_end')
        print(f'📸 [av_check] End screenshot: {end_shot or "none"}')

        # ---- the capture monitor's per-frame analysis for the window -------------
        frames, frames_error = load_window_frames(device, window_start, window_end)
        if frames_error:
            print(f'⚠️  [av_check] {frames_error}')
        rows = bucket_per_second(frames, window_start)
        print(f'📊 [av_check] {len(frames)} capture frames, {len(rows)} sampled seconds')

        # ---- motion between two frames (fullzap style) --------------------------
        # ZapExecutor.detect_real_motion runs the DetectMotion video verification
        # (two fresh frames + compare_images_for_motion) and adds the compared crops
        # to the context, so the report shows the exact frames behind the verdict.
        from shared.src.lib.executors.zap_executor import ZapExecutor
        zap_executor = ZapExecutor(
            device, args.userinterface,
            motion_area=motion_area,
            motion_threshold=motion_threshold,
            motion_duration=motion_window,
        )
        real_motion = zap_executor.detect_real_motion(context)
        motion_detected = bool(real_motion and real_motion.get('motion'))
        motion_change = real_motion.get('change') if real_motion else None
        motion_images = list(real_motion.get('images') or []) if real_motion else []
        print(f'🎬 [av_check] Motion: {"DETECTED" if motion_detected else "NOT DETECTED"}'
              f' ({motion_change if motion_change is not None else "n/a"}%)')

        # ---- verdicts ------------------------------------------------------------
        # A freeze is the gap in which the picture never changed, and a black screen
        # is a stretch of black frames. The longest of the two is the stall.
        freeze_windows = find_freeze_gaps(rows, max_freeze_s)
        black_windows = find_windows(rows, 'blackscreen')
        longest_stall = max([length for _, length in freeze_windows + black_windows] or [0])

        # Motion present = the share of the window in which the picture was not stuck
        # for longer than the tolerance. It is read from the same gaps the freeze
        # verdict uses, so the two always agree: a window with no gap over the
        # tolerance is a window in which the picture was alive.
        row_seconds = {row['second'] for row in rows}
        stuck = frozen_seconds(freeze_windows) & row_seconds
        if row_seconds:
            motion_pct = 100.0 * (len(row_seconds) - len(stuck)) / len(row_seconds)
        else:
            motion_pct = 0.0

        known_rows = [row for row in rows if row.get('audio_known')]
        if not known_rows:
            # The device captures no audio at all (VNC / emulator pipeline): the audio
            # verdict is not measurable, so it must not fail the run.
            audio_pct = None
            audio_pass = True
            audio_state = 'not measurable (this device captures no audio)'
        else:
            audible = sum(1 for row in known_rows if second_has_audio(row, audio_floor))
            audio_pct = (100.0 * audible / len(known_rows))
            audio_pass = audio_pct >= audio_min_present
            audio_state = f'{audio_pct:.1f}% of the window had sound (min {audio_min_present}%)'

        # Video PASS = motion seen and no freeze / black longer than the tolerance.
        # When the real 2-frame check could not run, fall back to the monitor's own
        # per-frame verdict (any clean second means the picture moved).
        no_signal_seconds = sum(1 for row in rows if row.get('no_signal'))
        if real_motion is None:
            video_pass = motion_pct > 0.0 and longest_stall <= max_freeze_s
            motion_note = 'no frame-to-frame check available'
        else:
            video_pass = motion_detected and longest_stall <= max_freeze_s
            motion_note = f'frame change {motion_change}% (threshold {motion_threshold}%)' \
                if motion_change is not None else 'frame change unknown'

        # The monitor's own no_signal flag: the device is not even connected to a
        # picture. Say that instead of the misleading "no motion".
        no_signal = bool(rows) and no_signal_seconds == len(rows)
        if no_signal:
            video_pass = False
            motion_note = f'no signal from the device for {no_signal_seconds}s'

        silence_windows = []
        if known_rows:
            for row in rows:
                if not row.get('audio_known') or second_has_audio(row, audio_floor):
                    continue
                if silence_windows and silence_windows[-1][0] + silence_windows[-1][1] == row['second']:
                    silence_windows[-1][1] += 1
                else:
                    silence_windows.append([row['second'], 1])

        peak_db = None
        levels = [row['mean_volume_db'] for row in rows
                  if isinstance(row.get('mean_volume_db'), (int, float))]
        if levels:
            peak_db = max(levels)

        video_pass_label = 'PASS' if video_pass else 'FAIL'
        audio_pass_label = 'PASS' if audio_pass else ('N/A' if audio_pct is None else 'FAIL')

        if audio_pct is None:
            audio_label = f'N/A - {audio_state}'
        elif peak_db is not None:
            audio_label = f'{audio_pass_label} - {audio_state}, peak {peak_db:.1f} dB'
        else:
            audio_label = f'{audio_pass_label} - {audio_state}'

        # "0.0% of the window" would be a lie when the device has no per-frame
        # analysis at all (a tv_lite / VNC capture): say so instead.
        motion_pct_txt = f'{motion_pct:.1f}% of the window' if rows else 'n/a (no per-frame analysis)'

        verdict.update({
            'sampled_s': len(rows),
            'watched_s': int(window_end - window_start),
            'motion_pct': motion_pct_txt,
            'video_label': f'{video_pass_label} - {motion_note}, motion present {motion_pct_txt}',
            'audio_label': audio_label,
            'silence_label': (f'{len(silence_windows)} ({format_windows([tuple(w) for w in silence_windows])})'
                              if silence_windows else 'none'),
            'freeze_label': (f'{len(freeze_windows) + len(black_windows)} '
                             f'(freeze: {format_windows(freeze_windows)}; '
                             f'black: {format_windows(black_windows)})'),
        })

        # ---- the report step ----------------------------------------------------
        shots = [shot for shot in (start_shot, mid_shot, end_shot) if shot]
        step = {
            'success': bool(video_pass and audio_pass),
            'from_node': args.node,
            'to_node': args.node,
            'step_category': 'av_check',
            'message': f'AV check on {node_name}: video {video_pass_label}, audio {audio_pass_label}',
            'execution_time_ms': int((window_end - window_start) * 1000),
            'start_time': window_start,
            'end_time': window_end,
            'motion_analysis': {
                'success': motion_detected,
                'change_percentage': motion_change,
                'real_motion_change': motion_change,
                'real_motion_threshold': motion_threshold,
                'real_motion_area': motion_area,
                'motion_analysis_images': motion_images,
            },
            'action_results': [
                {'message': 'av_watch_start', 'action_category': 'main', 'success': True,
                 'screenshot_path': shot}
                for shot in shots
            ],
            'action_screenshots': shots,
            # The evidence behind the audio verdict: the level of every second.
            # It is a table in the report, not a wall of text in the summary.
            'details_table': build_audio_table(rows, verdict),
            'details_table_title': 'AUDIO LEVEL PER SECOND',
        }
        if start_shot:
            step['step_start_screenshot_path'] = start_shot
        if end_shot:
            step['step_end_screenshot_path'] = end_shot
            step['screenshot_path'] = end_shot

        if not step['success']:
            reasons = []
            if not video_pass:
                if no_signal:
                    reasons.append('video: no signal from the device')
                elif real_motion is not None and not motion_detected:
                    reasons.append('video: no motion detected')
                else:
                    reasons.append(f'video: freeze/black window longer than {max_freeze_s}s')
            if not audio_pass:
                reasons.append(audio_reason(sound_state, audio_min_present))
            step['error'] = '; '.join(reasons)
        context.record_step_dict(step)

        context.overall_success = bool(video_pass and audio_pass)
        if not context.overall_success and not context.error_message:
            context.error_message = step.get('error') or 'AV check failed'
        return context.overall_success

    finally:
        context.execution_summary = build_summary(
            context, args, device, node_name, rows, verdict
        )


# Script arguments
main._script_args = _script_args
main._script_description = 'Watch a device for 30 s and judge video (moving, not frozen) and audio (present, not silent).'
main._arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': 'Optional variant name; if omitted, base data is used.',
    'node': 'Node that plays content with sound (YouTube player on web/mobile, live on an STB, the stream on an HLS device).',
    'duration': 'Seconds to watch the device before judging video and audio.',
    'settle-s': 'Seconds to wait after navigation before the watch window starts.',
    'motion-threshold': 'Minimum frame-to-frame change percentage to count as motion. Lower it when valid content is nearly static; raise it to reject overlay-only movement.',
    'motion-window-s': 'Seconds between the two frames the motion check compares (capped at 2.0).',
    'motion-area': 'Optional "x,y,width,height" region to compare, to exclude an animated overlay.',
    'audio-min-present': 'Minimum percentage of the watch window that must carry sound for the audio verdict to pass.',
    'audio-level-db': 'Mean volume (dB) a second must reach to count as audible. The platform default is -50 dB.',
    'prepare-audio': 'Put the sound up before the watch window: read the mute state the device can report, clear a mute on a browser player, and raise the volume to the maximum. The script never presses MUTE.',
    'volume-presses': 'How many VOLUME_UP presses bring the volume to the maximum.',
    'max-freeze-s': 'Longest freeze or black window (seconds) that still passes the video verdict.',
    'no-navigate': 'Watch the current screen instead of navigating to --node. A device with no remote, browser or desktop (an HLS / RTSP box) is watched automatically this way.',
    'verify': "Verification mode: 'end' (default, only destination), 'each' (every step), 'auto' (skip steps with edge+node confidence ≥ 0.7).",
}
main._target_rules = {
    # 'all': av_check runs on a device target (STB, phone, stream box) AND on the
    # host target of a browser box. 'device' would refuse the web device.
    'target_type': 'all',
    'host_os': 'all',
    'device_model': 'all',
}

if __name__ == '__main__':
    main()

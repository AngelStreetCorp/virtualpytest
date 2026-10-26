"""Unit tests for test_scripts/av_check.py (TASK-138). No device required.

The script's job is to say whether a device is really playing video and sound.
The part worth testing without a device is the per-second bucketing of the
capture monitor's per-frame JSON.

Two rules are tested here:

* the freeze / motion verdict for a second is built from what the platform
  *measured* - its per-frame pixel difference (`freeze_diffs`) and its verdict on it
  (`freeze`) - because the per-frame `freeze` flag only says "this frame looked like
  the one before it", which on a grabber that repeats the same picture flags a
  playing video as frozen on every repeat;
* a capture pipeline that writes no pixel difference at all falls back to the
  flags it does write, on the same majority rule the platform's own
  `analysis_utils.get_motion_analysis` uses.
"""

import importlib.util
import os

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "test_scripts", "av_check.py")


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("av_check", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _frames(rows, start=1000.0):
    """Build the frame list bucket_per_second() expects.

    `rows` is a list of (second_index, frames_in_that_second, analysis_json).
    """
    out = []
    for second, count, data in rows:
        for i in range(count):
            t = start + second + i * 0.05
            out.append({
                'file_mtime': int(t * 1000),
                'analysis_json': data,
            })
    return out


def test_single_frozen_frame_in_a_moving_second_is_not_a_freeze(mod):
    """One flagged frame out of five: the second is still moving."""
    frames = _frames([
        (0, 1, {'freeze': True}),
        (0, 4, {'freeze': False}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert len(rows) == 1
    assert rows[0]['freeze'] is False


def test_most_frames_frozen_marks_the_second_frozen(mod):
    """Four flagged frames out of five: the second really is frozen."""
    frames = _frames([
        (0, 4, {'freeze': True}),
        (0, 1, {'freeze': False}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['freeze'] is True


def test_fully_frozen_window_is_one_long_freeze_window(mod):
    """A device that never changes: every second frozen, one continuous window."""
    frames = _frames([(s, 5, {'freeze': True}) for s in range(6)])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert all(row['freeze'] for row in rows)
    windows = mod.find_windows(rows, 'freeze')
    assert len(windows) == 1
    assert windows[0][1] == len(rows)


def test_black_and_no_signal_use_the_same_majority_rule(mod):
    frames = _frames([
        (0, 5, {'blackscreen': True, 'no_signal': True}),
        (1, 5, {'blackscreen': False, 'no_signal': False}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['blackscreen'] is True
    assert rows[0]['no_signal'] is True
    assert rows[1]['blackscreen'] is False
    assert rows[1]['no_signal'] is False


def test_audio_keeps_the_last_known_value_of_the_second(mod):
    """The monitor snapshots the audio reading into every frame."""
    frames = _frames([
        (0, 5, {'audio': True, 'mean_volume_db': -20.0}),
        (1, 5, {'audio': None}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['audio'] is True
    assert rows[0]['mean_volume_db'] == -20.0
    # A second with no audio value at all stays unknown (the device captures no audio).
    frames2 = _frames([(0, 5, {'audio': None})])
    rows2 = mod.bucket_per_second(frames2, 1000.0)
    assert rows2[0]['audio'] is None
    assert rows2[0]['audio_known'] is False


def test_motion_comes_from_the_monitors_own_per_frame_verdict(mod):
    """'static' = the frame did not move, 'full' = it did."""
    frames = _frames([
        (0, 5, {'motion': {'kind': 'full', 'pct': 12.0}}),
        (1, 5, {'motion': {'kind': 'static', 'pct': 0.0}}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['motion'] is True
    assert rows[0]['motion_known'] is True
    assert rows[0]['motion_pct'] == 12.0
    assert rows[1]['motion'] is False


def test_a_static_second_is_not_motion_even_when_not_flagged_frozen(mod):
    """The freeze flag and the motion verdict answer different questions."""
    frames = _frames([
        (0, 5, {'freeze': False, 'motion': {'kind': 'static', 'pct': 0.0}}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['freeze'] is False
    assert rows[0]['motion'] is False


def test_capture_data_without_a_motion_field_stays_unknown(mod):
    """Older capture JSON has no 'motion' key: the row says so instead of guessing."""
    frames = _frames([(0, 5, {'freeze': False})])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['motion_known'] is False
    assert rows[0]['motion'] is False


# --- the measured-change rule -------------------------------------------------
# A phone on a slow HDMI mirror delivers the same picture for several frames in a
# row. The monitor flags every repeat as "frozen", so counting the flags reports a
# playing video as frozen for the whole window. The platform also writes the pixel
# difference it measured, and that is what the verdict is built on.

def test_one_measured_change_makes_the_second_moving(mod):
    """Four repeats and one real change: the picture moved during that second."""
    frames = _frames([
        (0, 4, {'freeze': True, 'freeze_diffs': [0.0, 0.0, 0.0]}),
        (0, 1, {'freeze': False, 'freeze_diffs': [3.09, 3.09, 3.09]}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['measured'] is True
    assert rows[0]['motion'] is True
    assert rows[0]['freeze'] is False


def test_a_second_where_nothing_changed_is_frozen(mod):
    """Every frame measured, every frame identical: the picture stood still."""
    frames = _frames([(0, 5, {'freeze': True, 'freeze_diffs': [0.0, 0.0, 0.0]})])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['measured'] is True
    assert rows[0]['motion'] is False
    assert rows[0]['freeze'] is True


def test_a_repeating_grabber_does_not_freeze_the_whole_window(mod):
    """The S7 case: 30 s of playback whose grabber repeats the picture."""
    frames = []
    for second in range(30):
        frames += _frames([
            (second, 4, {'freeze': True, 'freeze_diffs': [0.0, 0.0, 0.0]}),
            (second, 1, {'freeze': False, 'freeze_diffs': [3.09, 3.09, 3.09]}),
        ], start=1000.0)
    rows = mod.bucket_per_second(frames, 1000.0)
    assert len(rows) == 30
    assert all(row['motion'] for row in rows)
    assert not any(row['freeze'] for row in rows)
    assert mod.find_windows(rows, 'freeze') == []


def test_a_second_with_an_unmeasured_frame_is_not_called_frozen(mod):
    """We cannot say the picture stood still over a stretch we did not look at."""
    frames = _frames([
        (0, 4, {'freeze': True, 'freeze_diffs': [0.0, 0.0, 0.0]}),
        (0, 1, {'freeze': True}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['freeze'] is False
    assert rows[0]['motion'] is False


def test_a_black_frame_never_counts_as_motion(mod):
    """A black screen has no picture to compare: it is reported as black."""
    frames = _frames([
        (0, 5, {'freeze': False, 'blackscreen': True, 'freeze_diffs': [50.0, 50.0, 50.0]}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['blackscreen'] is True
    assert rows[0]['motion'] is False
    assert rows[0]['freeze'] is False


def test_a_no_signal_frame_never_counts_as_motion(mod):
    frames = _frames([
        (0, 5, {'freeze': False, 'no_signal': True, 'freeze_diffs': [50.0, 50.0, 50.0]}),
    ])
    rows = mod.bucket_per_second(frames, 1000.0)
    assert rows[0]['no_signal'] is True
    assert rows[0]['motion'] is False
    assert rows[0]['freeze'] is False


def test_the_measured_change_is_read_from_the_platforms_own_numbers(mod):
    """frame_change_verdict reads the monitor's diffs and its verdict on them."""
    assert mod.frame_change_verdict({'freeze_diffs': [0.0, 0.0, 0.0], 'freeze': True}) is False
    assert mod.frame_change_verdict({'freeze_diffs': [3.09], 'freeze': False}) is True
    # No measurement at all -> unknown, never a guess.
    assert mod.frame_change_verdict({'freeze': True}) is None
    assert mod.frame_change_verdict({'freeze_diffs': [], 'freeze': True}) is None
    assert mod.frame_change_verdict({'freeze_diffs': [1.0], 'freeze': None}) is None


# --- the freeze is the gap between two changes ---------------------------------
# The S7's grabber shows a new picture every 1-2 s, so most one-second buckets hold
# no change at all. Counting "the seconds without a change" calls that device
# frozen; reading the freeze as the gap between two changes does not.

def _changed_every(seconds, changed_at, start=1000.0):
    """Frames whose picture changed in the seconds listed in `changed_at`."""
    frames = []
    for second in seconds:
        data = ({'freeze': False, 'freeze_diffs': [3.09, 3.09, 3.09]}
                if second in changed_at
                else {'freeze': True, 'freeze_diffs': [0.0, 0.0, 0.0]})
        frames += _frames([(second, 5, data)], start=start)
    return frames


def test_a_slowly_updating_picture_is_not_frozen(mod):
    """A new picture every 2 s: the device is alive, there is no freeze."""
    seconds = list(range(30))
    rows = mod.bucket_per_second(_changed_every(seconds, seconds), 1000.0)
    assert mod.find_freeze_gaps(rows, 5.0) == []


def test_a_picture_that_stops_leaves_one_long_gap(mod):
    """The picture changes up to s10 and then stands still: one 19 s gap."""
    seconds = list(range(30))
    rows = mod.bucket_per_second(_changed_every(seconds, range(0, 11)), 1000.0)
    windows = mod.find_freeze_gaps(rows, 5.0)
    assert windows == [(11, 19)]


def test_a_picture_that_never_changes_is_one_gap_over_the_window(mod):
    seconds = list(range(30))
    rows = mod.bucket_per_second(_changed_every(seconds, []), 1000.0)
    assert mod.find_freeze_gaps(rows, 5.0) == [(0, 30)]


def test_a_gap_shorter_than_the_tolerance_is_not_a_freeze(mod):
    """A 4 s gap with a 5 s tolerance is tolerated."""
    seconds = list(range(30))
    rows = mod.bucket_per_second(_changed_every(seconds, [0, 5, 10, 15, 20, 25]), 1000.0)
    assert mod.find_freeze_gaps(rows, 5.0) == []


def test_the_frozen_seconds_are_the_ones_the_gap_covers(mod):
    assert mod.frozen_seconds([(11, 19)]) == set(range(11, 30))
    assert mod.frozen_seconds([]) == set()


# ---------------------------------------------------------------------------
# The sound: the mute state, the volume, and the reason the report gives.
# ---------------------------------------------------------------------------


class _FakeRemote:
    """A remote that accepts some keys and counts the presses."""

    def __init__(self, keys=('VOLUME_UP',)):
        self.keys = keys
        self.pressed = []

    def press_key(self, key):
        self.pressed.append(key)
        return key in self.keys


class _FakeDevice:
    """A device with the controllers a test needs."""

    def __init__(self, remote=None, web=None):
        self._remote = remote
        self._web = web

    def has_controller(self, kind):
        return {'remote': self._remote, 'web': self._web}.get(kind) is not None

    def _get_controller(self, kind):
        return {'remote': self._remote, 'web': self._web}.get(kind)


def test_the_volume_is_raised_to_the_maximum_before_the_watch(mod):
    """A volume at 0 is a reason for silence: the check puts it up first."""
    remote = _FakeRemote()
    state = mod.prepare_audio(_FakeDevice(remote=remote), 20)
    assert state['volume'] == 20
    assert remote.pressed == ['VOLUME_UP'] * 20
    assert state['muted'] is None          # the device cannot say


def test_the_check_never_presses_mute(mod):
    """The script must not create the silence it then reports."""
    remote = _FakeRemote(keys=('VOLUME_UP', 'MUTE'))
    mod.prepare_audio(_FakeDevice(remote=remote), 20)
    assert 'MUTE' not in remote.pressed


def test_a_device_without_a_remote_keeps_its_volume(mod):
    state = mod.prepare_audio(_FakeDevice(), 20)
    assert state['volume'] == 0
    assert state['muted'] is None


def test_the_sound_line_says_when_the_device_cannot_tell(mod):
    assert mod.sound_label({'muted': None}) == 'this device does not report a mute state'
    assert mod.sound_label({'muted': False}) == 'the device is not muted'
    assert mod.sound_label({'muted': True}) == 'the device is muted'
    assert mod.sound_label({'muted': True, 'unmuted': True}) == \
        'the player was muted and was unmuted before the check'


def test_the_volume_line_is_empty_when_nothing_was_done(mod):
    assert mod.volume_label({'volume': 0}) == ''
    assert mod.volume_label({'volume': 20}) == 'raised to the maximum (20 x VOLUME_UP)'


def test_a_muted_device_is_reported_as_muted_and_not_as_no_sound(mod):
    """The reason names the cause the check knows."""
    assert mod.audio_reason({'muted': True}, 60.0) == 'audio: the device is muted'


def test_a_silent_device_that_is_not_muted_says_so(mod):
    reason = mod.audio_reason({'muted': False, 'volume': 20}, 60.0)
    assert reason.startswith('audio: present for less than 60.0% of the window')
    assert 'the device is not muted' in reason


def test_a_silent_device_with_an_unknown_mute_state_says_that(mod):
    reason = mod.audio_reason({'muted': None, 'volume': 20}, 60.0)
    assert 'the volume was raised to the maximum, the mute state is unknown' in reason


def test_the_summary_is_short_and_carries_no_per_second_lines(mod):
    """The executive summary is the verdict - the levels live in the table."""
    class _Host:
        host_name = 'vpt-pi1'

    class _Ctx:
        host = _Host()
        screenshot_paths = ['a', 'b']
        overall_success = False
        error_message = ''

    class _Device:
        device_name = 'stb4'
        device_model = 'stb_tv'

    class _Args:
        userinterface = 'stb_tv'

    rows = [{'second': i, 'mean_volume_db': -91.0, 'audio': False, 'audio_known': True}
            for i in range(30)]
    verdict = {
        'variant': 'base', 'watched_s': 30, 'sampled_s': 30,
        'video_label': 'PASS', 'audio_label': 'FAIL', 'sound_label': 'the device is muted',
        'volume_label': 'raised to the maximum (20 x VOLUME_UP)',
        'silence_label': '1 (s0-29 (30s))', 'freeze_label': '0 (freeze: none; black: none)',
        'motion_pct': '100.0% of the window', 'navigation_label': 'navigated to the target',
        'audio_floor': -50.0,
    }
    summary = mod.build_summary(_Ctx(), _Args(), _Device(), 'live', rows, verdict)
    assert len(summary.split('\n')) <= 20
    assert 'AUDIO LEVEL PER SECOND' not in summary
    assert 's29' not in summary
    assert '🔈 Sound: the device is muted' in summary
    assert '🔉 Volume: raised to the maximum (20 x VOLUME_UP)' in summary


def test_the_audio_evidence_is_a_table_with_a_row_per_second(mod):
    rows = [
        {'second': 0, 'mean_volume_db': -91.0, 'audio': False, 'audio_known': True},
        {'second': 1, 'mean_volume_db': -22.6, 'audio': True, 'audio_known': True},
        {'second': 2, 'mean_volume_db': None, 'audio': None, 'audio_known': False},
    ]
    table = mod.build_audio_table(rows, {'audio_floor': -50.0})
    assert table['headers'] == ['Second', 'Level', 'Sound']
    assert table['rows'] == [
        ['s0', '-91.0 dB', 'silent'],
        ['s1', '-22.6 dB', 'audio present'],
        ['s2', 'N/A', 'unknown'],
    ]


def test_the_report_shows_the_audio_table_next_to_the_step():
    """The step carries the table; the report renders it as a table."""
    from shared.src.lib.utils.report_step_formatter import format_step_details_table

    html = format_step_details_table({
        'details_table_title': 'AUDIO LEVEL PER SECOND',
        'details_table': {
            'headers': ['Second', 'Level', 'Sound'],
            'rows': [['s0', '-91.0 dB', 'silent'], ['s1', '-22.6 dB', 'audio present']],
        },
    })
    assert '<table class="details-table">' in html
    assert '<th>Second</th>' in html
    assert '<td>s0</td>' in html
    assert '<td>-91.0 dB</td>' in html
    assert '<td>silent</td>' in html


def test_a_step_without_a_table_renders_nothing():
    from shared.src.lib.utils.report_step_formatter import format_step_details_table

    assert format_step_details_table({}) == ''
    assert format_step_details_table({'details_table': {'headers': ['a'], 'rows': []}}) == ''

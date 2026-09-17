"""
tests/backend_host/test_phone_ui_verification.py — the watch pair on
PhoneAgentAdbVerificationController (`waitForElementToChange` /
`waitForElementToStopChanging`).

These answer "is this playing?" from the player's own position label instead of from motion
in the captured frames: directly, in about a second, rather than sampling pixels for up to a
minute — and without mistaking a player that has not started drawing yet for one that is
stuck (BUG-0121 follow-up).

The bridge is scripted rather than real: the cases that matter are about *timing* — a label
that moves, one that holds, one that disappears mid-watch when YouTube hides its controls —
and none of them can be staged reliably against a live phone.

ADBVerificationController is exercised at the end through the same shared `element_watch`,
because youtube-android-mobile targets android_mobile AND phone_agent: whichever of the two a
tree was not written for is the one where a missing command shows up.

Run:
    cd <worktree> && PYTHONPATH=. python3 -m pytest tests/backend_host -q
"""
import importlib
import time

import pytest

phone_ui = importlib.import_module(
    'features.mobile-app.backend_host.controllers.phone_ui_verification')
adb_verification = importlib.import_module(
    'backend_host.src.controllers.verification.adb')
PhoneAgentAdbVerificationController = phone_ui.PhoneAgentAdbVerificationController
ADBVerificationController = adb_verification.ADBVerificationController

# Two readings of a YouTube player's scrubber, three seconds apart, exactly as the phone
# reports them.
PLAYING_AT = "21 minutes 0 seconds of 1 hour 3 minutes 38 seconds"
PLAYING_LATER = "21 minutes 3 seconds of 1 hour 3 minutes 38 seconds"


def seekbar(label):
    return {'class': 'android.widget.SeekBar', 'content_desc': label, 'text': '',
            'resource_id': '', 'bounds': [0, 900, 1080, 960], 'id': 7}


class ScriptedBridge:
    """Hands out the next screen on each dump, then repeats the last one forever."""

    def __init__(self, screens):
        self.screens = list(screens)
        self.calls = 0

    def rpc(self, device_id, name, params, timeout):
        screen = self.screens[min(self.calls, len(self.screens) - 1)]
        self.calls += 1
        return {'ok': True, 'result': {'elements': screen}}


def controller(screens):
    ctrl = PhoneAgentAdbVerificationController.__new__(PhoneAgentAdbVerificationController)
    ctrl.device_id = 'device2'
    ctrl.device_model = 'phone_agent'
    ctrl.bridge = ScriptedBridge(screens)
    return ctrl


class ScriptedAdbUtils:
    """dump_elements as adb_utils would answer it, over the same scripted screens."""

    def __init__(self, screens):
        self.screens = list(screens)
        self.calls = 0
        self.reasons = []

    def dump_elements(self, device_id, reason='dump'):
        # `reason` mirrors the real ADBUtils.dump_elements, which labels each dump for the
        # execution's UI trace. Kept in the double so the two signatures cannot drift apart.
        self.reasons.append(reason)
        screen = self.screens[min(self.calls, len(self.screens) - 1)]
        self.calls += 1
        return True, [_AsAndroidElement(e) for e in screen], ''


class _AsAndroidElement:
    """Only what getElementLists() touches: to_dict()."""

    def __init__(self, element):
        self._element = element

    def to_dict(self):
        return dict(self._element)


def adb_controller(screens):
    """The same watch, reached through ADBVerificationController.

    youtube-android-mobile targets android_mobile AND phone_agent, so both controllers have to
    answer these commands or the tree breaks on whichever device it was not written for.
    """
    ctrl = ADBVerificationController.__new__(ADBVerificationController)
    ctrl.device_id = 'emulator-5554'
    ctrl.adb_utils = ScriptedAdbUtils(screens)
    return ctrl


# ---- waitForElementToChange -------------------------------------------------------------

def test_moving_position_passes_on_the_tick_not_at_the_timeout():
    ctrl = controller([[seekbar(PLAYING_AT)], [seekbar(PLAYING_AT)], [seekbar(PLAYING_LATER)]])
    started = time.time()
    ok, message, details = ctrl.waitForElementToChange('SeekBar', 20.0)
    assert ok, message
    # The whole point of polling rather than sampling twice: it answers as soon as the
    # position moves, well inside the few seconds a player shows its controls.
    assert time.time() - started < 5
    assert details['first_label'] == PLAYING_AT
    assert details['last_label'] == PLAYING_LATER
    assert details['changed'] is True


def test_a_paused_player_fails_and_says_what_it_held_at():
    ctrl = controller([[seekbar(PLAYING_AT)]])
    ok, message, details = ctrl.waitForElementToChange('SeekBar', 2.0)
    assert not ok
    assert 'held at' in message
    assert details['timeout_reached'] is True
    assert details['first_label'] == PLAYING_AT


def test_never_finding_the_element_reads_differently_from_finding_a_still_one():
    """"I never saw a SeekBar" usually means the selector or the screen is wrong; "it stood
    still" means playback. The messages must not be confusable."""
    ctrl = controller([[]])
    ok, message, details = ctrl.waitForElementToChange('SeekBar', 2.0)
    assert not ok
    assert 'no element matching' in message
    assert details['first_label'] == ''


def test_controls_may_hide_and_come_back_changed():
    """YouTube takes its controls — and the SeekBar with them — off the tree after a few
    seconds. The baseline survives that, so a later reading still settles the question."""
    ctrl = controller([[seekbar(PLAYING_AT)], [], [], [seekbar(PLAYING_LATER)]])
    ok, message, details = ctrl.waitForElementToChange('SeekBar', 20.0)
    assert ok, message
    assert details['first_label'] == PLAYING_AT
    assert details['last_label'] == PLAYING_LATER


def test_an_element_with_no_label_is_reported_not_treated_as_stable():
    ctrl = controller([[{'class': 'android.widget.SeekBar', 'content_desc': '', 'text': ''}]])
    ok, message, _ = ctrl.waitForElementToChange('SeekBar', 1.5)
    assert not ok
    assert 'no label to watch' in message


# ---- waitForElementToStopChanging -------------------------------------------------------

def test_a_steady_label_settles():
    ctrl = controller([[seekbar(PLAYING_AT)]])
    ok, message, _ = ctrl.waitForElementToStopChanging('SeekBar', 1.0, 10.0)
    assert ok, message
    assert 'held at' in message


def test_a_moving_label_never_settles():
    ctrl = controller([[seekbar(PLAYING_AT)], [seekbar(PLAYING_LATER)],
                       [seekbar(PLAYING_AT)], [seekbar(PLAYING_LATER)]])
    ok, _, _ = ctrl.waitForElementToStopChanging('SeekBar', 3.0, 3.0)
    assert not ok


# ---- execute_verification, i.e. how a tree calls it --------------------------------------

def test_timeout_arrives_in_milliseconds_from_a_tree():
    ctrl = controller([[seekbar(PLAYING_AT)], [seekbar(PLAYING_LATER)]])
    result = ctrl.execute_verification({
        'command': 'waitForElementToChange',
        'verification_type': 'adb',
        'params': {'search_term': 'SeekBar', 'timeout': 20000},
    })
    assert result['success'], result['message']


def test_a_nonsense_timeout_cannot_hang_a_run():
    ctrl = controller([[seekbar(PLAYING_AT)]])
    started = time.time()
    result = ctrl.execute_verification({
        'command': 'waitForElementToStopChanging',
        'verification_type': 'adb',
        'params': {'search_term': 'SeekBar', 'duration': 1.0, 'timeout': 999_000_000},
    })
    assert result['success']
    assert time.time() - started < 10


# ---- what the executor requires of an 'adb' verification ---------------------------------

def test_declared_params_survive_the_executors_filter():
    """VerificationExecutor._filter_valid_verifications drops any 'adb' verification with no
    search_term before it reaches a controller, so these must declare one."""
    ctrl = controller([[]])
    declared = {v['command']: v for v in ctrl.get_available_verifications()}
    assert {'waitForElementToChange', 'waitForElementToStopChanging'} <= set(declared)
    for verification in declared.values():
        assert verification['verification_type'] == 'adb'
        assert verification['params']['search_term'].get('required') is True

    # Only the "has it settled?" side has a window to configure; the change side polls.
    assert 'duration' in declared['waitForElementToStopChanging']['params']
    assert 'duration' not in declared['waitForElementToChange']['params']


@pytest.mark.parametrize('command', ['waitForElementToChange', 'waitForElementToStopChanging'])
def test_a_missing_search_term_is_refused_rather_than_guessed(command):
    ctrl = controller([[seekbar(PLAYING_AT)]])
    result = ctrl.execute_verification({'command': command, 'verification_type': 'adb',
                                        'params': {}})
    assert result['success'] is False


# ---- the adb controller answers identically ----------------------------------------------

def test_adb_controller_sees_a_moving_position_too():
    ctrl = adb_controller([[seekbar(PLAYING_AT)], [seekbar(PLAYING_LATER)]])
    ok, message, details = ctrl.waitForElementToChange('SeekBar', 20.0)
    assert ok, message
    assert details['first_label'] == PLAYING_AT
    assert details['last_label'] == PLAYING_LATER


def test_adb_controller_dispatches_both_commands():
    """A tree records the command name; ADBVerificationController used to answer 'Unknown ADB
    verification command' for these, which is how the tree would have broken on a real device."""
    ctrl = adb_controller([[seekbar(PLAYING_AT)], [seekbar(PLAYING_LATER)]])
    result = ctrl.execute_verification({
        'command': 'waitForElementToChange',
        'verification_type': 'adb',
        'params': {'search_term': 'SeekBar', 'timeout': 20000},
    })
    assert result['success'], result['message']

    ctrl = adb_controller([[seekbar(PLAYING_AT)]])
    result = ctrl.execute_verification({
        'command': 'waitForElementToStopChanging',
        'verification_type': 'adb',
        'params': {'search_term': 'SeekBar', 'duration': 1.0, 'timeout': 20000},
    })
    assert result['success'], result['message']


def test_both_controllers_declare_the_same_watch_commands():
    phone = {v['command'] for v in controller([[]]).get_available_verifications()}
    adb = {v['command'] for v in adb_controller([[]]).get_available_verifications()}
    watch = {'waitForElementToChange', 'waitForElementToStopChanging'}
    assert watch <= phone and watch <= adb

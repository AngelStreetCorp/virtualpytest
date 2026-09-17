"""
tests/backend_host/test_phone_launch_reset.py — `launch_app(reset=True)` on a paired phone.

Why it exists: `close_app` on a phone can only press HOME. Unrooted Android has no force-stop
API, so close-then-launch means "go to the launcher, then put the app back exactly as it was".
On YouTube that is the watch page rather than the feed, and a tree whose first step verifies
the feed's bottom nav fails on a screen that never had one. `reset` asks Android to clear the
app's task on launch instead, which needs no permission.

The parameter is off by default and omitted from the payload entirely when false, so an agent
that predates it behaves exactly as before — both directions of that compatibility are checked
here, because the APK and the host are deployed independently.
"""
import importlib

import pytest

phone_agent = importlib.import_module(
    'features.mobile-app.backend_host.controllers.phone_agent')
protocol = importlib.import_module('features.mobile-app.lib.protocol')
PhoneAgentRemoteController = phone_agent.PhoneAgentRemoteController


class RecordingBridge:
    """Accepts every command and remembers the payloads."""

    def __init__(self):
        self.calls = []

    def rpc(self, device_id, name, params=None, timeout=None):
        self.calls.append((name, dict(params or {})))
        return {'ok': True, 'result': {}}

    def get_slot(self, device_id):
        return None


@pytest.fixture
def controller():
    ctrl = PhoneAgentRemoteController.__new__(PhoneAgentRemoteController)
    ctrl.device_id = 'device2'
    ctrl.device_name = 'samsung SM-G998B'
    # Normally set by RemoteControllerInterface.__init__, which __new__ skips.
    ctrl.device_type = 'phone_agent'
    ctrl.bridge = RecordingBridge()
    ctrl.last_error = None
    ctrl.last_click_label = None
    ctrl.last_ui_elements = []
    ctrl.last_dump_time = 0.0
    return ctrl


def test_a_plain_launch_sends_no_reset_key_at_all(controller):
    """Not `reset: false` — absent. An older agent reads an unknown key as false either way,
    but sending nothing keeps the payload identical to what it has always been."""
    assert controller.launch_app('com.google.android.youtube') is True
    name, params = controller.bridge.calls[-1]
    assert name == protocol.CMD_LAUNCH_APP
    assert params == {'package': 'com.google.android.youtube'}


def test_reset_is_sent_when_asked(controller):
    assert controller.launch_app('com.google.android.youtube', reset=True) is True
    _, params = controller.bridge.calls[-1]
    assert params == {'package': 'com.google.android.youtube', 'reset': True}


@pytest.mark.parametrize('value,expected', [
    (True, True), ('true', True), ('True', True), ('yes', True), (1, True), ('1', True),
    (False, False), ('false', False), ('', False), (None, False), (0, False),
])
def test_execute_command_reads_reset_the_way_a_tree_stores_it(controller, value, expected):
    """A tree's params survive a JSON round trip, so a boolean can arrive as a string."""
    controller.execute_command('launch_app',
                               {'package': 'com.example.app', 'reset': value})
    _, params = controller.bridge.calls[-1]
    assert ('reset' in params) is expected


def test_execute_command_without_reset_is_unchanged(controller):
    controller.execute_command('launch_app', {'package': 'com.example.app'})
    _, params = controller.bridge.calls[-1]
    assert params == {'package': 'com.example.app'}


def test_restart_app_is_offered_only_as_a_preset_of_launch_app(controller):
    """It is the same command with the flag set, not a new one the agent must know."""
    remote = controller.get_available_actions()['Remote']
    restart = next(a for a in remote if a['id'] == 'restart_app')
    assert restart['command'] == 'launch_app'
    assert restart['params']['reset'] is True
    assert restart['inputParam'] == 'package'

    # and the plain Launch App is still there, unchanged
    launch = next(a for a in remote if a['id'] == 'launch_app')
    assert 'reset' not in launch['params']


def test_the_action_catalogue_still_excludes_what_a_phone_cannot_do(controller):
    commands = {a['command'] for a in controller.get_available_actions()['Remote']}
    assert 'capture_camera_image' not in commands

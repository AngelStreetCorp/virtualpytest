"""
tests/backend_host/test_appium_android_parity.py — an Appium Android phone must run an
`android_mobile` navigation tree unchanged.

MODEL_FAMILIES (shared/src/lib/config/device_capabilities.py) puts `android_mobile`,
`phone_agent` and `cloud_android_mobile` in one family, so every matcher now offers an
`android_mobile` userinterface for a cloud farm phone. That promise is only true if the
Appium side answers the same commands the adb side does. Two gaps were closed for it:

* the swipe family (`swipe`, `swipe_up/down/left/right`) — recorded in most mobile trees,
  and previously Unknown command on Appium;
* `waitForElementToChange` / `waitForElementToStopChanging` — the element-watch
  verifications shared with the adb controller and the paired-phone one via element_watch.

features/mobile-app made the same guarantee for a paired phone by reusing
AndroidMobileRemoteController's catalogue outright; the Appium controller cannot inherit
it, so the parity is asserted here instead.
"""
import pytest

appium_remote = pytest.importorskip(
    'backend_host.src.controllers.remote.appium_remote',
    reason='backend_host runtime not installed here')
android_mobile = pytest.importorskip(
    'backend_host.src.controllers.remote.android_mobile')
appium_verification = pytest.importorskip(
    'backend_host.src.controllers.verification.appium')
appium_utils_mod = pytest.importorskip('backend_host.src.lib.utils.appium_utils')

AppiumElement = appium_utils_mod.AppiumElement

SWIPE_COMMANDS = ('swipe', 'swipe_up', 'swipe_down', 'swipe_left', 'swipe_right')


class FakeUtils:
    """Stands in for AppiumUtils: records swipes and dumps, never touches a device."""

    def __init__(self, screens=None):
        self.swipes = []
        self.screens = list(screens or [])
        self.dumps = 0

    def swipe(self, device_id, from_x, from_y, to_x, to_y, duration=300):
        self.swipes.append((from_x, from_y, to_x, to_y, duration))
        return True

    def dump_elements(self, device_id):
        # The last screen repeats once the script runs out, so a poll settles.
        screen = self.screens[self.dumps] if self.dumps < len(self.screens) else (
            self.screens[-1] if self.screens else [])
        self.dumps += 1
        return True, list(screen), ''


def element(text='', content_desc='', element_id='1'):
    return AppiumElement(
        id=element_id, text=text, className='android.widget.SeekBar',
        package='io.virtualpytest.app', contentDesc=content_desc,
        bounds={'left': 0, 'top': 0, 'right': 10, 'bottom': 10},
        clickable=True, enabled=True, focused=False, selected=False,
        platform='android', resource_id='')


def _commands(actions):
    """Every command in an action catalogue, whatever the category is called.

    android_mobile files its list under 'Remote' and the Appium controller under
    'remote'; this comparison is about the commands, not that spelling.
    """
    return {action['command'] for entries in actions.values() for action in entries}


@pytest.fixture
def remote():
    c = appium_remote.AppiumRemoteController('Android', 'device4', 'http://farm/wd/hub')
    c.is_connected = True
    c.detected_platform = 'android'
    c.appium_utils = FakeUtils()
    return c


@pytest.fixture
def verification():
    c = appium_verification.AppiumVerificationController(
        appium_platform_name='Android', appium_device_id='device4')
    c.is_connected = True
    return c


# ---- remote: the swipe family ------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize('command', SWIPE_COMMANDS)
def test_every_android_mobile_swipe_is_offered_by_the_appium_controller(remote, command):
    """A tree's action picker is built from get_available_actions, so a missing entry
    means the action cannot be recorded against a farm phone in the first place."""
    offered = {a['command'] for a in remote.get_available_actions()['remote']}
    assert command in offered


@pytest.mark.unit
@pytest.mark.parametrize('command', SWIPE_COMMANDS[1:])
def test_a_directional_swipe_runs_without_parameters(remote, command):
    """Trees record these with no params at all — the defaults have to carry them."""
    assert remote.execute_command(command)['success'] is True
    assert len(remote.appium_utils.swipes) == 1


@pytest.mark.unit
def test_a_vertical_swipe_stays_vertical(remote):
    """android_mobile pins X for up/down; a diagonal gesture scrolls the wrong list."""
    remote.execute_command('swipe_up', {'from_x': 400})
    from_x, _, to_x, _, _ = remote.appium_utils.swipes[0]
    assert from_x == to_x == 400


@pytest.mark.unit
def test_a_horizontal_swipe_stays_horizontal(remote):
    remote.execute_command('swipe_left', {'from_y': 900})
    _, from_y, _, to_y, _ = remote.appium_utils.swipes[0]
    assert from_y == to_y == 900


@pytest.mark.unit
def test_a_custom_swipe_passes_its_coordinates_through(remote):
    remote.execute_command('swipe', {'from_x': 10, 'from_y': 20, 'to_x': 30, 'to_y': 40,
                                     'duration': 500})
    assert remote.appium_utils.swipes == [(10, 20, 30, 40, 500)]


@pytest.mark.unit
def test_a_custom_swipe_missing_a_coordinate_fails_rather_than_guessing(remote):
    assert remote.execute_command('swipe', {'from_x': 10, 'from_y': 20})['success'] is False
    assert remote.appium_utils.swipes == []


@pytest.mark.unit
def test_the_appium_catalogue_covers_the_android_mobile_one(remote):
    """The family promise, stated as a set comparison.

    `capture_camera_image` is excluded for the same reason features/mobile-app excludes
    it for a paired phone: it needs `adb shell am start` plus a file pull, which neither
    a paired phone nor a leased farm session has an equivalent for.
    """
    android = _commands(android_mobile.AndroidMobileRemoteController.get_available_actions(None))
    offered = _commands(remote.get_available_actions())
    missing = android - offered - {'capture_camera_image'}
    assert not missing, f'an android_mobile tree could record {sorted(missing)} and it would not run'


# ---- verification: the element-watch commands --------------------------------------

@pytest.mark.unit
def test_wait_for_element_to_change_passes_when_the_label_moves(verification):
    """A player's own position answers "is this playing?" without looking at pixels."""
    verification.appium_utils = FakeUtils([
        [element(content_desc='0:05')],
        [element(content_desc='0:09')],
    ])
    result = verification.execute_verification({
        'command': 'waitForElementToChange',
        'params': {'search_term': 'SeekBar', 'timeout': 5000},
    })
    assert result['success'] is True


@pytest.mark.unit
def test_wait_for_element_to_stop_changing_passes_on_a_still_label(verification):
    verification.appium_utils = FakeUtils([[element(content_desc='0:05')]])
    result = verification.execute_verification({
        'command': 'waitForElementToStopChanging',
        'params': {'search_term': 'SeekBar', 'timeout': 5000, 'duration': 0.1},
    })
    assert result['success'] is True


@pytest.mark.unit
def test_the_watch_commands_read_appium_spelling_of_content_desc(verification):
    """AppiumElement.to_dict says `contentDesc`; element_watch searches `content_desc`.

    Without the translation the search matches nothing and every watch verification
    fails with "no element matching" on a screen that plainly has it.
    """
    shaped = appium_verification.AppiumVerificationController._adb_shaped(
        {'contentDesc': 'Play', 'className': 'android.widget.Button'})
    assert shaped['content_desc'] == 'Play'
    assert shaped['class_name'] == 'android.widget.Button'


@pytest.mark.unit
def test_an_unknown_verification_command_is_still_refused(verification):
    """The new branches must not turn the else into a catch-all."""
    verification.appium_utils = FakeUtils([[element(text='Settings')]])
    result = verification.execute_verification({
        'command': 'waitForSomethingNobodyImplemented',
        'params': {'search_term': 'Settings'},
    })
    assert result['success'] is False
    assert 'Unsupported command' in result['details']['error']

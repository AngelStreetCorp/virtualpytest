"""
tests/backend_host/test_appium_click_dumps_first.py — click_element must look at the
screen as it is now, not at whatever was dumped earlier.

`AppiumRemoteController.click_element` resolves a label through three helpers
(find_element_by_text / _by_identifier / _by_content_desc) and all three read
`self.last_ui_elements`. Only `dump_elements` ever fills that list, so a click on a
freshly built controller used to search an EMPTY list and report "Element not found"
for something plainly on screen.

The adb remote never had this: its click_element takes a fresh dump first
("dump-first approach"). The Appium one now does the same.

Why it mattered enough to test: a navigation tree's click action never dumps first,
and on a cloud farm device there is no adb path to fall back on — so every
click_element in a tree failed there. Found driving the VirtualPyTest app on a Sauce
Labs device, 2026-09-17.
"""
import types

import pytest

appium_remote = pytest.importorskip(
    'backend_host.src.controllers.remote.appium_remote',
    reason='backend_host runtime not installed here')
appium_utils_mod = pytest.importorskip('backend_host.src.lib.utils.appium_utils')

AppiumElement = appium_utils_mod.AppiumElement


def make_element(text, element_id='1'):
    return AppiumElement(
        id=element_id, text=text, className='android.widget.Button',
        package='io.virtualpytest.app', contentDesc='',
        bounds={'left': 0, 'top': 0, 'right': 10, 'bottom': 10},
        clickable=True, enabled=True, focused=False, selected=False,
        platform='android', resource_id='')


class FakeUtils:
    """Stands in for AppiumUtils: records dumps and clicks, never touches a device."""

    def __init__(self, screen):
        self.screen = screen
        self.dumps = 0
        self.clicked = []

    def dump_elements(self, device_id):
        self.dumps += 1
        return True, list(self.screen), ''

    def click_element(self, device_id, element):
        self.clicked.append(element.text)
        return True


@pytest.fixture
def controller():
    c = appium_remote.AppiumRemoteController('Android', 'device4', 'http://farm/wd/hub')
    c.is_connected = True
    c.detected_platform = 'android'
    return c


def test_a_click_on_a_fresh_controller_finds_what_is_on_screen(controller):
    """The regression: last_ui_elements is empty until something dumps."""
    controller.appium_utils = FakeUtils([make_element('Settings', '36')])
    assert controller.last_ui_elements == []

    assert controller.click_element('Settings') is True
    assert controller.appium_utils.clicked == ['Settings']


def test_the_click_dumps_before_searching(controller):
    controller.appium_utils = FakeUtils([make_element('Settings')])
    controller.click_element('Settings')
    assert controller.appium_utils.dumps == 1


def test_a_stale_cache_does_not_decide_the_click(controller):
    """A label that has left the screen must not still be clickable from the cache."""
    controller.appium_utils = FakeUtils([make_element('Dashboard')])
    controller.last_ui_elements = [make_element('Settings')]   # yesterday's screen

    assert controller.click_element('Settings') is False
    assert controller.appium_utils.clicked == []


def test_one_dump_serves_every_fallback_term(controller):
    """Pipe-separated terms are fallbacks against ONE screen, so one dump, not three."""
    controller.appium_utils = FakeUtils([make_element('Options')])
    assert controller.click_element('Settings|Preferences|Options') is True
    assert controller.appium_utils.dumps == 1
    assert controller.appium_utils.clicked == ['Options']


def test_a_failed_dump_is_not_fatal(controller):
    """If the dump fails the click still tries the previous list rather than raising."""
    utils = FakeUtils([])

    def failing_dump(device_id):
        utils.dumps += 1
        return False, [], 'device not answering'

    utils.dump_elements = failing_dump
    controller.appium_utils = utils
    controller.last_ui_elements = [make_element('Settings')]

    assert controller.click_element('Settings') is True
    assert utils.clicked == ['Settings']


def test_click_element_by_id_also_dumps_first(controller):
    """Same trap, same fix: `click_element_by_id` resolves an id against the dump.

    A tree's action never dumps beforehand, so on a fresh controller the id was looked
    up in an empty list and the click silently did nothing. Reached parity review when
    android_mobile and cloud_android_mobile became one model family.
    """
    controller.appium_utils = FakeUtils([make_element('Settings', '8')])
    assert controller.last_ui_elements == []

    result = controller.execute_command('click_element_by_id', {'element_id': '8'})

    assert result['success'] is True
    assert controller.appium_utils.dumps == 1
    assert controller.appium_utils.clicked == ['Settings']


def test_click_element_by_id_does_not_trust_a_stale_dump(controller):
    """An id that belonged to yesterday's screen must not still be clickable."""
    controller.appium_utils = FakeUtils([make_element('Dashboard', '3')])
    controller.last_ui_elements = [make_element('Settings', '8')]

    assert controller.execute_command('click_element_by_id', {'element_id': '8'})['success'] is False
    assert controller.appium_utils.clicked == []

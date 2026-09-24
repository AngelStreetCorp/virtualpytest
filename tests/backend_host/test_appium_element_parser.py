"""
tests/backend_host/test_appium_element_parser.py — the two XML shapes a dump arrives in.

`_parse_android_elements` is fed by two different producers. ADB's `uiautomator dump`
names every element <node …>; Appium's own `page_source` names each one after its
class (<android.widget.Button …>). The parser was written against the first shape only,
so it returned zero elements for the second — silently, because an empty tree is a
legitimate answer.

That mattered the day a cloud farm device ran a real session: a farm phone has no ADB,
so `page_source` is the only dump available there, and every verification and selector
saw an empty screen. Confirmed against a live Sauce Labs device 2026-09-17, where the
same screen went from 0 elements to 38.
"""
import importlib

import pytest

appium_utils = pytest.importorskip(
    'backend_host.src.lib.utils.appium_utils',
    reason='backend_host runtime not installed here')

parse = appium_utils.AppiumUtils()._parse_android_elements


# The shape Appium returns: the class is the tag, and neither resource-id nor
# content-desc is present at all — the filter has to survive their absence.
APPIUM_SOURCE = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy index="0" class="hierarchy" rotation="0" width="1080" height="2340">
  <android.widget.FrameLayout index="0" package="io.virtualpytest.app" class="android.widget.FrameLayout" text="" clickable="false" enabled="true" bounds="[0,0][1080,2340]" displayed="true">
    <android.widget.Button index="1" package="io.virtualpytest.app" class="android.widget.Button" text="Run" clickable="true" enabled="true" bounds="[10,20][300,90]" displayed="true" />
    <android.widget.TextView index="2" package="io.virtualpytest.app" class="android.widget.TextView" text="Dashboard" clickable="false" enabled="true" bounds="[0,100][500,200]" displayed="true"></android.widget.TextView>
  </android.widget.FrameLayout>
</hierarchy>"""

# The shape ADB returns, which has to keep working.
ADB_SOURCE = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node index="0" text="Hi" resource-id="io.virtualpytest.app:id/title" class="android.widget.TextView" package="io.virtualpytest.app" content-desc="" clickable="false" enabled="true" bounds="[0,0][100,50]" />
</hierarchy>"""


def test_appium_page_source_is_parsed_not_silently_empty():
    """The regression: class-named tags used to match nothing and return an empty screen."""
    elements = parse(APPIUM_SOURCE)
    assert elements, 'Appium page_source parsed to zero elements'
    texts = [e.text for e in elements]
    assert 'Run' in texts and 'Dashboard' in texts


def test_adb_node_dumps_still_parse():
    elements = parse(ADB_SOURCE)
    assert len(elements) == 1
    assert elements[0].text == 'Hi'
    assert elements[0].resource_id == 'io.virtualpytest.app:id/title'


def test_the_hierarchy_root_is_not_an_element():
    """<hierarchy> carries class="hierarchy", which would otherwise pass the filter."""
    assert all(e.className != 'hierarchy' for e in parse(APPIUM_SOURCE))


def test_a_child_attribute_does_not_bleed_into_its_parent():
    """The old `>.*?</node>` form searched a parent's whole subtree for each attribute,
    so a container with no text of its own inherited the first child's."""
    parent = [e for e in parse(APPIUM_SOURCE)
              if e.className == 'android.widget.FrameLayout']
    assert parent and parent[0].text == ''


def test_bounds_survive_the_parse():
    button = [e for e in parse(APPIUM_SOURCE) if e.text == 'Run'][0]
    assert button.bounds == {'left': 10, 'top': 20, 'right': 300, 'bottom': 90}
    assert button.clickable is True

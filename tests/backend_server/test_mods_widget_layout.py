"""Widget layout shape check (features/mods/lib/widget_layout.py, TASK-77). Offline, pure."""

import pytest

from features.mods.lib.widget_layout import MAX_WIDGETS, clean_layout, valid_area

pytestmark = pytest.mark.unit


def test_a_valid_layout_is_kept_as_is():
    layout = [{'id': 'w-1', 'widgetId': 'team-devices', 'settings': {'show': 'all', 'compact': True}}]
    assert clean_layout(layout) == (layout, None)


def test_unknown_keys_are_dropped_and_missing_settings_become_empty():
    cleaned, why = clean_layout([{'id': 'w-1', 'widgetId': 'x', 'extra': 'dropped'}])
    assert why is None
    assert cleaned == [{'id': 'w-1', 'widgetId': 'x', 'settings': {}}]


@pytest.mark.parametrize('layout', [
    'not a list',
    [{'widgetId': 'x'}],
    [{'id': 'w', 'widgetId': 'x', 'settings': {'n': 3}}],
    [{'id': 'w', 'widgetId': 'x', 'settings': {'s': {'nested': 1}}}],
    [{'id': f'w{i}', 'widgetId': 'x'} for i in range(MAX_WIDGETS + 1)],
])
def test_bad_shapes_are_refused(layout):
    cleaned, why = clean_layout(layout)
    assert cleaned is None and why


def test_only_known_areas():
    assert valid_area('dashboard')
    assert not valid_area('anything')
    assert not valid_area(None)

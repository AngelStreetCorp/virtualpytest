"""DUP_FP audit flag: two nodes of one interface with the same stored focus and title (TASK-133)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'localize'))
import audit  # noqa: E402


def _n(label, x, title='q home tv', kind='nav', width=0.026, ui='stb-testop'):
    return {'userinterface_name': ui, 'label': label,
            'fingerprint': {'title': title, 'focus': {'kind': kind, 'x': x, 'width': width}}}


def test_same_underline_and_title_is_flagged():
    flags = audit.dup_fp_flags([_n('home_settings', 0.896), _n('tvguide', 0.896), _n('home_profile', 0.933)])
    assert flags == ['DUP_FP stb-testop: home_settings/tvguide']


def test_different_tab_or_title_is_not():
    assert audit.dup_fp_flags([_n('a', 0.2), _n('b', 0.5)]) == []
    assert audit.dup_fp_flags([_n('a', 0.2), _n('b', 0.2, title='tv guide')]) == []


def test_no_title_no_focus_and_fixtures_are_skipped():
    assert audit.dup_fp_flags([_n('a', 0.2, title=''), _n('b', 0.2, title='')]) == []
    assert audit.dup_fp_flags([_n('a', 0.2, ui='__fixture__'), _n('b', 0.2, ui='__fixture__')]) == []

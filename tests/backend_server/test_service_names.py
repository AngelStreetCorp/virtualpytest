from shared.src.lib.utils.service_names import LEGACY_UNIT_NAMES, canonical_unit_name


def test_old_names_map_to_new():
    assert canonical_unit_name('vpt-monitor') == 'vpt-monitor-img'
    assert canonical_unit_name('vpt-transcript') == 'vpt-monitor-audio'
    assert canonical_unit_name('vpt-subtitle') == 'vpt-monitor-subtitle'


def test_other_names_pass_through():
    assert canonical_unit_name('vpt-host') == 'vpt-host'
    assert canonical_unit_name('vpt-monitor-img') == 'vpt-monitor-img'
    assert set(LEGACY_UNIT_NAMES.values()) == {'vpt-monitor-img', 'vpt-monitor-audio', 'vpt-monitor-subtitle'}

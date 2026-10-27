"""G3 — accepting an unknown screen preserves its complete v6 fingerprint.

`build_unknown_node_data` is the payload the accept route saves. It must carry
the row's full v6 blob when present and a legacy ``{dhash}`` unchanged.
"""
import importlib

import pytest

node_mod = importlib.import_module('shared.src.lib.utils.unknown_screen_node')

pytestmark = pytest.mark.unit

V6 = {
    'v': 6, 'dhash': 'ab' * 32,
    'regions': {'full': 'ab' * 32, 'center': 'cd' * 32},
    'crop': None, 'focus': {'kind': 'nav', 'x': 0.5}, 'title': 'settings', 'text': [],
}


def test_full_v6_fingerprint_is_stored_on_the_node():
    row = {'fingerprint': V6, 'proposed_name': 'settings_menu',
           'image_url': '/host/h1/stream/capture/captures/x.jpg', 'dom': {'screen_type': 'menu'}}
    data = node_mod.build_unknown_node_data(row, 'stb-testop', 'row-1')
    assert data['data']['fingerprint'] == V6
    assert data['node_id'] == 'settings_menu'
    assert data['data']['screenshot'] == row['image_url']
    assert data['data']['from_unknown_screen'] == 'row-1'


def test_legacy_dhash_fingerprint_is_preserved_unchanged():
    row = {'fingerprint': {'dhash': 'abc'}, 'proposed_name': 'old_screen'}
    data = node_mod.build_unknown_node_data(row, 'stb-testop', 'row-2')
    assert data['data']['fingerprint'] == {'dhash': 'abc'}


def test_label_fallback_and_sanitized_id():
    row = {'proposed_name': None}
    data = node_mod.build_unknown_node_data(row, 'stb-testop', 'abcdef12-3456-7890')
    assert data['label'] == 'stb-testop_unknown_abcdef12'
    assert data['node_id'] == 'stb_testop_unknown_abcdef12'


def test_explicit_label_wins():
    data = node_mod.build_unknown_node_data(
        {'fingerprint': V6, 'proposed_name': 'ai_name'}, 'stb-testop', 'row-3', label='Human Name')
    assert data['label'] == 'Human Name'
    assert data['node_id'] == 'human_name'

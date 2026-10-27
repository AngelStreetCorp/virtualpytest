"""Unit tests for the auto-classify scheduler (TASK-115).

The picker (above-threshold rows), the bump_attempts (read-then-write
fallback), the prune RPC, the interface options and the upsert_proposal —
all against a mock supabase client. The hybrid classifier (classify_screen /
classify_open) is stubbed via monkeypatch.
"""
import os
import sys
import types
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from backend_server.scripts import auto_classify_unknowns  # noqa: E402


def test_pick_candidates_uses_threshold_and_attempts(monkeypatch):
    fake_db = MagicMock()
    # Build the chain that ends in .execute() and return a representative payload.
    chain = fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .is_.return_value.or_.return_value.gte.return_value.lt.return_value
    chain.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value \
        = types.SimpleNamespace(data=[
            {'id': 'r1', 'dhash': 'abc', 'scope': 'h1/d1',
             'seen_count': 8, 'sample_image_path': '/tmp/a.png',
             'classification_attempts': 0, 'last_seen': '2026-10-16T08:00:00Z'},
        ])
    out = auto_classify_unknowns.pick_candidates(fake_db, 't1', threshold=5)
    assert len(out) == 1
    assert out[0]['seen_count'] == 8


def test_bump_attempts_increments_monotonically(monkeypatch):
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .limit.return_value.execute.return_value = types.SimpleNamespace(data=[
        {'classification_attempts': 2}
    ])
    auto_classify_unknowns.bump_attempts(fake_db, 't1', 'row-1')
    update_call = fake_db.table.return_value.update.call_args.args[0]
    assert update_call['classification_attempts'] == 3


def test_bump_attempts_silent_on_missing_row(monkeypatch):
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .limit.return_value.execute.return_value = types.SimpleNamespace(data=[])
    auto_classify_unknowns.bump_attempts(fake_db, 't1', 'row-missing')
    # No update call was made — missing row stays missing.
    assert not fake_db.table.return_value.update.called


def test_upsert_proposal_writes_minimal_payload(monkeypatch):
    fake_db = MagicMock()
    fake_db.table.return_value.upsert.return_value.execute.return_value \
        = types.SimpleNamespace(data=[{'id': 'u1'}])
    ok = auto_classify_unknowns.upsert_proposal(
        fake_db, 't1',
        {'dhash': 'abc', 'scope': 'h1/d1', 'userinterface': 'stb-testop', 'seen_count': 7,
         'sample_image_path': '/tmp/a.png'},
        {'screen_type': 'dialog', 'screen_summary': 'subscription expired'},
        'dialog_subscription_expired',
    )
    assert ok is True
    call = fake_db.table.return_value.upsert.call_args
    payload = call.args[0]
    assert payload['userinterface'] == 'stb-testop'
    assert payload['proposed_name'] == 'dialog_subscription_expired'
    assert payload['classification'] == 'unknown'
    assert payload['frame_count'] == 7


def test_prune_noise_calls_rpc_with_team_id(monkeypatch):
    fake_db = MagicMock()
    fake_db.rpc.return_value.execute.return_value = types.SimpleNamespace(
        data=[{'deleted_count': 42}]
    )
    n = auto_classify_unknowns.prune_noise(fake_db, 't1')
    assert n == 42
    rpc_call = fake_db.rpc.call_args
    assert rpc_call.args[0] == 'prune_unnamed_screen_noise'
    assert rpc_call.args[1]['p_team_id'] == 't1'


def test_classify_one_skips_missing_sample(monkeypatch, tmp_path):
    row = {'sample_image_path': str(tmp_path / 'does_not_exist.png')}
    out = auto_classify_unknowns.classify_one(row, 't1')
    assert out == {'ok': False, 'no_sample': True}


def test_classify_one_returns_label(monkeypatch, tmp_path):
    img = tmp_path / 'frame.png'
    img.write_bytes(b'fake')
    monkeypatch.setattr(auto_classify_unknowns, 'classify_open',
                        lambda path, team_id: {'ok': True, 'source': 'qwen',
                                               'label': 'volume_slider'})
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': str(img)}, 't1'
    )
    assert out['ok'] is True
    assert out['label'] == 'volume_slider'


def _patch_fetch(monkeypatch, data, reason=None, capture=None):
    from backend_server.src.mcp.tools import screenshot_tools

    def fake(url, host_name=None):
        if capture is not None:
            capture.update(url=url, host_name=host_name)
        return data, reason

    monkeypatch.setattr(screenshot_tools, '_fetch_screenshot_bytes', fake)


def test_resolve_sample_path_local_file(tmp_path):
    img = tmp_path / 'frame.png'
    img.write_bytes(b'x')
    path, reason = auto_classify_unknowns.resolve_sample_path(str(img))
    assert path == str(img)
    assert reason is None


def test_resolve_sample_path_missing_file(tmp_path):
    path, reason = auto_classify_unknowns.resolve_sample_path(str(tmp_path / 'gone.png'))
    assert path is None
    assert 'not a local path' in reason


def test_resolve_sample_path_blank():
    path, reason = auto_classify_unknowns.resolve_sample_path(None)
    assert path is None
    assert 'no sample' in reason


def test_resolve_sample_path_relative_host_url_fetches(monkeypatch):
    captured = {}
    _patch_fetch(monkeypatch, b'\xff\xd8\xff\xe0fake-jpeg', capture=captured)
    path, reason = auto_classify_unknowns.resolve_sample_path(
        '/host/h1/stream/capture1/captures/capture_0001.jpg', scope='h1/stb-testop')
    assert path and os.path.exists(path) and reason is None
    assert captured['url'].startswith('/host/h1/')
    assert captured['host_name'] == 'h1'
    os.unlink(path)


def test_classify_one_fetches_live_url_and_cleans_temp(monkeypatch):
    seen = {}
    _patch_fetch(monkeypatch, b'\xff\xd8\xff\xe0fake-jpeg')

    def fake_classify(path, team_id=None):
        seen['path'] = path
        seen['exists_during'] = os.path.exists(path)
        return {'ok': True, 'source': 'qwen', 'label': 'volume_slider'}

    monkeypatch.setattr(auto_classify_unknowns, 'classify_open', fake_classify)
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': '/host/h1/stream/capture1/captures/capture_0001.jpg',
         'scope': 'h1/stb-testop', 'dhash': 'abc'}, 't1')
    assert out['ok'] is True
    assert seen['exists_during'] is True
    assert not os.path.exists(seen['path'])  # temp file removed after classification


def test_classify_one_absolute_url_fetches(monkeypatch):
    captured = {}
    _patch_fetch(monkeypatch, b'\x89PNG\r\n\x1a\nfake-png', capture=captured)
    monkeypatch.setattr(auto_classify_unknowns, 'classify_open',
                        lambda path, team_id=None: {'ok': True, 'source': 'qwen',
                                                    'label': 'main_menu'})
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': 'https://example.test/frame.png', 'scope': 'h1/d1', 'dhash': 'abc'}, 't1')
    assert out['ok'] is True
    assert captured['url'] == 'https://example.test/frame.png'


def test_classify_one_expired_sample_returns_none(monkeypatch):
    _patch_fetch(monkeypatch, None, reason='HTTP 404 from host h1')
    calls = {'n': 0}

    def fake_classify(*args, **kwargs):
        calls['n'] += 1
        return {}

    monkeypatch.setattr(auto_classify_unknowns, 'classify_open', fake_classify)
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': '/host/h1/stream/capture1/captures/capture_0001.jpg',
         'scope': 'h1/d1', 'dhash': 'abc'}, 't1')
    assert out == {'ok': False, 'no_sample': True}
    assert calls['n'] == 0


def test_classify_one_missing_sample_returns_none(monkeypatch, tmp_path):
    calls = {'n': 0}

    def fake_classify(*args, **kwargs):
        calls['n'] += 1
        return {}

    monkeypatch.setattr(auto_classify_unknowns, 'classify_open', fake_classify)
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': str(tmp_path / 'missing.jpg'), 'scope': 'h1/d1', 'dhash': 'abc'}, 't1')
    assert out == {'ok': False, 'no_sample': True}
    assert calls['n'] == 0


def test_classify_one_error_result_returns_none(monkeypatch):
    _patch_fetch(monkeypatch, b'\xff\xd8\xff\xe0fake-jpeg')
    monkeypatch.setattr(auto_classify_unknowns, 'classify_open',
                        lambda path, team_id=None: {'ok': False,
                                                    'error': 'not an image'})
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': '/host/h1/stream/capture1/captures/capture_0001.jpg',
         'scope': 'h1/d1', 'dhash': 'abc'}, 't1')
    assert out is None


def test_resolve_sample_path_host_local_path_maps_to_host_route(monkeypatch):
    captured = {}
    _patch_fetch(monkeypatch, b'\xff\xd8\xff\xe0fake-jpeg', capture=captured)
    path, reason = auto_classify_unknowns.resolve_sample_path(
        '/var/www/html/stream/capture/hot/captures/capture_000535741.jpg', scope='h1/stb-testop')
    assert path and os.path.exists(path) and reason is None
    assert captured['url'] == '/host/h1/stream/capture/captures/capture_000535741.jpg'
    assert captured['host_name'] == 'h1'
    os.unlink(path)


def test_resolve_sample_path_host_local_without_scope_skips():
    path, reason = auto_classify_unknowns.resolve_sample_path(
        '/var/www/html/stream/capture/hot/captures/capture_000535741.jpg', scope=None)
    assert path is None
    assert 'not a local path' in reason


V6 = {
    'v': 6, 'dhash': 'ab' * 32,
    'regions': {'full': 'ab' * 32, 'center': 'cd' * 32},
    'crop': None, 'focus': {'kind': 'none'}, 'title': 'settings', 'text': [],
}


def test_pick_candidates_selects_the_fingerprint_column():
    fake_db = MagicMock()
    chain = fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .is_.return_value.or_.return_value.gte.return_value.lt.return_value
    chain.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value \
        = types.SimpleNamespace(data=[])
    auto_classify_unknowns.pick_candidates(fake_db, 't1', threshold=5)
    select_arg = fake_db.table.return_value.select.call_args.args[0]
    assert 'fingerprint' in select_arg


def test_upsert_proposal_preserves_full_fingerprint():
    fake_db = MagicMock()
    fake_db.table.return_value.upsert.return_value.execute.return_value \
        = types.SimpleNamespace(data=[{'id': 'u1'}])
    ok = auto_classify_unknowns.upsert_proposal(
        fake_db, 't1',
        {'dhash': 'ab' * 32, 'scope': 'h1/d1', 'userinterface': 'stb-testop', 'seen_count': 7,
         'sample_image_path': '/host/h1/x.jpg', 'fingerprint': V6},
        {'screen_type': 'menu', 'screen_summary': 'main menu'}, 'main_menu')
    assert ok is True
    payload = fake_db.table.return_value.upsert.call_args.args[0]
    assert payload['fingerprint'] == V6


def test_upsert_proposal_legacy_row_falls_back_to_dhash():
    fake_db = MagicMock()
    fake_db.table.return_value.upsert.return_value.execute.return_value \
        = types.SimpleNamespace(data=[{'id': 'u1'}])
    auto_classify_unknowns.upsert_proposal(
        fake_db, 't1',
        {'dhash': 'abc', 'scope': 'h1/d1', 'userinterface': 'stb-testop', 'seen_count': 7,
         'sample_image_path': '/host/h1/x.jpg'},
        {'screen_type': 'menu', 'screen_summary': 'main menu'}, 'main_menu')
    payload = fake_db.table.return_value.upsert.call_args.args[0]
    assert payload['fingerprint'] == {'dhash': 'abc'}


def test_run_once_dry_run_no_writes(monkeypatch):
    """Dry-run lists candidates but does not call LLM or write."""
    fake_db = MagicMock()
    chain = fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .is_.return_value.or_.return_value.gte.return_value.lt.return_value
    chain.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value \
        = types.SimpleNamespace(data=[
            {'id': 'r1', 'dhash': 'abc', 'scope': 'h1/d1',
             'seen_count': 9, 'sample_image_path': '/tmp/a.png',
             'classification_attempts': 0, 'last_seen': '2026-10-16T08:00:00Z'},
        ])
    fake_db.rpc.return_value.execute.return_value = types.SimpleNamespace(data=[{'deleted_count': 0}])
    monkeypatch.setattr(auto_classify_unknowns, 'get_supabase_client', lambda: fake_db)
    monkeypatch.setattr(auto_classify_unknowns, 'local_host_names', lambda: {'h1'})

    stats = auto_classify_unknowns.run_once('t1', threshold=5, apply=False, prune=True)
    assert stats['picked'] == 1
    # Dry-run: no insert into userinterface_unknown_screens, no LLM call.
    assert stats['proposed'] == 0
    assert stats['failed'] == 0


def _result(rows):
    return types.SimpleNamespace(data=rows)


def _fake_db(results):
    """Minimal supabase chain: table(...).select(...).eq(...).in_(...).limit(...).execute()."""

    class Chain:
        def __init__(self, res):
            self._res = res

        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return self._res

    class DB:
        def table(self, name): return Chain(results[name])

    return DB()


def test_interface_options_returns_real_fingerprinted_nodes():
    db = _fake_db({
        'userinterfaces': _result([{'id': 'ui1'}]),
        'navigation_trees': _result([{'id': 'tree1'}]),
        'navigation_nodes': _result([
            {'node_id': 'settings', 'label': 'Settings', 'node_type': 'screen', 'dhash': 'aa'},
            {'node_id': 'home', 'label': None, 'node_type': 'screen', 'dhash': 'bb'},
            {'node_id': 'entry', 'label': 'Entry', 'node_type': 'entry', 'dhash': 'cc'},
            {'node_id': 'legacy', 'label': 'Legacy', 'node_type': 'screen', 'dhash': None},
            {'node_id': 'settings', 'label': 'Settings dup', 'node_type': 'screen', 'dhash': 'dd'},
        ]),
    })
    out = auto_classify_unknowns.interface_options(db, 't1', 'stb_ui')
    assert out == [{'id': 'home', 'description': 'home'},
                   {'id': 'settings', 'description': 'Settings'}]


def test_interface_options_empty_for_a_legacy_row_or_unknown_interface():
    assert auto_classify_unknowns.interface_options(None, 't1', None) == []
    db = _fake_db({'userinterfaces': _result([])})
    assert auto_classify_unknowns.interface_options(db, 't1', 'ghost') == []


def test_row_userinterface_prefers_the_recorded_interface():
    assert auto_classify_unknowns.row_userinterface(
        {'scope': 'h1/stb-testop', 'userinterface': 'stb_ui'}) == 'stb_ui'
    # G6: the device part of the scope is no interface
    assert auto_classify_unknowns.row_userinterface({'scope': 'h1/stb-testop'}) == ''


def test_pick_candidates_selects_the_userinterface_column():
    fake_db = MagicMock()
    chain = fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .is_.return_value.or_.return_value.gte.return_value.lt.return_value
    chain.not_.is_.return_value.order.return_value.limit.return_value.execute.return_value \
        = types.SimpleNamespace(data=[])
    auto_classify_unknowns.pick_candidates(fake_db, 't1', threshold=5)
    assert 'userinterface' in fake_db.table.return_value.select.call_args.args[0]


def test_classify_one_passes_the_interface_options(monkeypatch, tmp_path):
    img = tmp_path / 'frame.png'
    img.write_bytes(b'x')
    seen = {}

    def fake(path, team_id, options=None):
        seen['options'] = options
        return {'ok': True, 'source': 'qwen', 'label': 'settings'}

    monkeypatch.setattr(auto_classify_unknowns, 'classify_screen', fake)
    opts = [{'id': 'settings', 'description': 'Settings'}]
    auto_classify_unknowns.classify_one({'sample_image_path': str(img)}, 't1',
                                        options=opts, mode='hybrid')
    assert seen['options'] == opts


def test_classify_one_jev_none_uses_the_open_label(monkeypatch, tmp_path):
    img = tmp_path / 'frame.png'
    img.write_bytes(b'x')
    monkeypatch.setattr(auto_classify_unknowns, 'classify_screen',
                        lambda *a, **k: {'ok': True, 'source': 'qwen', 'label': 'netflix_home',
                                         'jev': {'ok': True, 'source': 'jev', 'choice': 'none'}})
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': str(img)}, 't1',
        options=[{'id': 'settings', 'description': 'Settings'}], mode='hybrid')
    assert out['label'] == 'netflix_home'
    assert 'known_node_id' not in out['dom']


def test_classify_one_jev_error_uses_the_open_label(monkeypatch, tmp_path):
    img = tmp_path / 'frame.png'
    img.write_bytes(b'x')
    monkeypatch.setattr(auto_classify_unknowns, 'classify_screen',
                        lambda *a, **k: {'ok': True, 'source': 'qwen', 'label': 'menu',
                                         'jev': {'ok': False, 'source': 'jev', 'error': 'down'}})
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': str(img)}, 't1',
        options=[{'id': 'settings', 'description': 'Settings'}], mode='hybrid')
    assert out['label'] == 'menu'
    assert 'known_node_id' not in out['dom']


def test_classify_one_valid_node_uses_the_real_label(monkeypatch, tmp_path):
    img = tmp_path / 'frame.png'
    img.write_bytes(b'x')
    monkeypatch.setattr(auto_classify_unknowns, 'classify_screen',
                        lambda *a, **k: {'ok': True, 'source': 'jev', 'choice': 'settings'})
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': str(img)}, 't1',
        options=[{'id': 'settings', 'description': 'Settings'}], mode='hybrid')
    assert out['label'] == 'Settings'
    assert out['dom']['known_node_id'] == 'settings'


def test_classify_one_invalid_node_falls_back_to_open(monkeypatch, tmp_path):
    """A node id the interface does not have must never become a name."""
    img = tmp_path / 'frame.png'
    img.write_bytes(b'x')
    calls = {'open': 0}
    monkeypatch.setattr(auto_classify_unknowns, 'classify_screen',
                        lambda *a, **k: {'ok': True, 'source': 'jev', 'choice': 'ghost'})

    def fake_open(path, team_id):
        calls['open'] += 1
        return {'ok': True, 'source': 'qwen', 'label': 'mystery_screen'}

    monkeypatch.setattr(auto_classify_unknowns, 'classify_open', fake_open)
    out = auto_classify_unknowns.classify_one(
        {'sample_image_path': str(img)}, 't1',
        options=[{'id': 'settings', 'description': 'Settings'}], mode='hybrid')
    assert calls['open'] == 1
    assert out['label'] == 'mystery_screen'
    assert 'known_node_id' not in out['dom']


def test_upsert_proposal_uses_the_recorded_interface_and_stays_pending():
    fake_db = MagicMock()
    fake_db.table.return_value.upsert.return_value.execute.return_value \
        = types.SimpleNamespace(data=[{'id': 'u1'}])
    ok = auto_classify_unknowns.upsert_proposal(
        fake_db, 't1',
        {'dhash': 'abc', 'scope': 'h1/stb-testop', 'userinterface': 'stb_ui',
         'seen_count': 7, 'sample_image_path': '/tmp/a.png'},
        {'screen_type': None}, 'settings')
    assert ok is True
    payload = fake_db.table.return_value.upsert.call_args.args[0]
    assert payload['userinterface'] == 'stb_ui'
    assert payload['status'] == 'pending'
    assert payload['classification'] == 'unknown'


def test_upsert_proposal_keeps_the_captured_fingerprint_for_a_known_node_choice():
    """A chosen node id must never supply the proposal's fingerprint."""
    fake_db = MagicMock()
    fake_db.table.return_value.upsert.return_value.execute.return_value \
        = types.SimpleNamespace(data=[{'id': 'u1'}])
    auto_classify_unknowns.upsert_proposal(
        fake_db, 't1',
        {'dhash': V6['dhash'], 'scope': 'h1/stb-testop', 'userinterface': 'stb_ui',
         'seen_count': 7, 'sample_image_path': '/host/h1/x.jpg', 'fingerprint': V6},
        {'screen_type': None, 'screen_summary': 'Settings',
         'known_node_id': 'settings'}, 'Settings')
    payload = fake_db.table.return_value.upsert.call_args.args[0]
    assert payload['fingerprint'] == V6
    assert payload['dom']['known_node_id'] == 'settings'
    assert payload['status'] == 'pending'


def test_run_once_apply_passes_the_row_interface_and_only_upserts(monkeypatch):
    row = {'id': 'r1', 'dhash': 'abc', 'scope': 'h1/stb-testop', 'userinterface': 'stb_ui',
           'seen_count': 9, 'sample_image_path': '/tmp/a.png', 'classification_attempts': 0}
    seen = {}
    monkeypatch.setattr(auto_classify_unknowns, 'get_supabase_client', lambda: object())
    monkeypatch.setattr(auto_classify_unknowns, 'pick_candidates', lambda db, t, th: [row])
    monkeypatch.setattr(auto_classify_unknowns, 'local_host_names', lambda: {'h1'})

    def fake_options(db, team_id, ui):
        seen['ui'] = ui
        return [{'id': 'settings', 'description': 'Settings'}]

    monkeypatch.setattr(auto_classify_unknowns, 'interface_options', fake_options)

    def fake_classify(r, team_id, options=None, mode='qwen'):
        seen['options'] = options
        seen['mode'] = mode
        return {'dom': {'screen_type': None, 'screen_summary': 'x'}, 'label': 'x', 'ok': True}

    monkeypatch.setattr(auto_classify_unknowns, 'classify_one', fake_classify)

    def fake_upsert(db, team_id, r, dom, label):
        seen['upsert'] = {'row': r, 'dom': dom, 'label': label}
        return True

    monkeypatch.setattr(auto_classify_unknowns, 'upsert_proposal', fake_upsert)
    monkeypatch.setattr(auto_classify_unknowns, 'bump_attempts', lambda *a: None)
    monkeypatch.setattr(auto_classify_unknowns, 'name_row', lambda *a: True)

    stats = auto_classify_unknowns.run_once('t1', 5, apply=True, prune=False,
                                             classifier='hybrid')
    assert stats == {'picked': 1, 'proposed': 1, 'failed': 0, 'pruned': 0,
                     'skipped_remote': 0, 'named': 1}
    assert seen['ui'] == 'stb_ui'
    assert seen['mode'] == 'hybrid'
    assert seen['options'] == [{'id': 'settings', 'description': 'Settings'}]
    assert seen['upsert']['label'] == 'x'


def test_team_id_falls_back_to_the_app_default(monkeypatch):
    monkeypatch.delenv('VIRTUALPYTEST_TEAM_ID', raising=False)
    monkeypatch.setenv('TEAM_ID', 'team-default')
    assert auto_classify_unknowns._team_id_arg() == 'team-default'


def test_team_id_prefers_the_auto_classify_env(monkeypatch):
    monkeypatch.setenv('VIRTUALPYTEST_TEAM_ID', 'team-cron')
    monkeypatch.setenv('TEAM_ID', 'team-default')
    assert auto_classify_unknowns._team_id_arg() == 'team-cron'


def test_team_id_empty_unit_env_falls_back(monkeypatch):
    """The shipped unit sets VIRTUALPYTEST_TEAM_ID= (empty): use the default."""
    monkeypatch.setenv('VIRTUALPYTEST_TEAM_ID', '')
    monkeypatch.setenv('TEAM_ID', 'team-default')
    assert auto_classify_unknowns._team_id_arg() == 'team-default'


def test_local_host_names_reads_the_registry(monkeypatch):
    from backend_server.src.lib.utils import server_utils

    class FakeManager:
        def get_all_hosts(self):
            return {'host-clone-1': {}, 'labox-mobile': {}}

    monkeypatch.setattr(server_utils, 'get_host_manager', lambda: FakeManager())
    assert auto_classify_unknowns.local_host_names() == {'host-clone-1', 'labox-mobile'}


def test_run_once_skips_remote_rows_without_attempts(monkeypatch):
    remote = {'id': 'r2', 'dhash': 'def', 'scope': 'vpt-pi4/host', 'seen_count': 9,
              'sample_image_path': '/host/vpt-pi4/x.jpg', 'classification_attempts': 0}
    local = {'id': 'r1', 'dhash': 'abc', 'scope': 'host-clone-1/stb4', 'seen_count': 9,
             'sample_image_path': '/tmp/a.png', 'classification_attempts': 0}
    calls = {'classify': [], 'bump': [], 'mode': []}
    monkeypatch.setattr(auto_classify_unknowns, 'get_supabase_client', lambda: object())
    monkeypatch.setattr(auto_classify_unknowns, 'pick_candidates',
                        lambda db, t, th: [remote, local])
    monkeypatch.setattr(auto_classify_unknowns, 'local_host_names', lambda: {'host-clone-1'})
    monkeypatch.setattr(auto_classify_unknowns, 'interface_options', lambda db, t, ui: [])
    def fake_classify(r, team, options=None, mode='qwen'):
        calls['classify'].append(r['id'])
        calls['mode'].append(mode)
        return {'dom': {}, 'label': 'x', 'ok': True}

    monkeypatch.setattr(auto_classify_unknowns, 'classify_one', fake_classify)
    monkeypatch.setattr(auto_classify_unknowns, 'upsert_proposal', lambda *a: True)
    monkeypatch.setattr(auto_classify_unknowns, 'bump_attempts',
                        lambda db, t, rid: calls['bump'].append(rid))

    stats = auto_classify_unknowns.run_once('t1', 5, apply=True, prune=False)
    assert calls['classify'] == ['r1']
    assert calls['mode'] == ['qwen']        # default path, no Jev
    assert calls['bump'] == ['r1']          # the remote row's attempts are untouched
    assert stats['picked'] == 1 and stats['skipped_remote'] == 1


def test_run_once_with_no_local_hosts_classifies_nothing(monkeypatch):
    row = {'id': 'r1', 'dhash': 'abc', 'scope': 'vpt-pi4/host', 'seen_count': 9,
           'sample_image_path': '/host/vpt-pi4/x.jpg', 'classification_attempts': 0}
    monkeypatch.setattr(auto_classify_unknowns, 'get_supabase_client', lambda: object())
    monkeypatch.setattr(auto_classify_unknowns, 'pick_candidates', lambda db, t, th: [row])
    monkeypatch.setattr(auto_classify_unknowns, 'local_host_names', lambda: set())
    monkeypatch.setattr(auto_classify_unknowns, 'classify_one',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not classify')))
    stats = auto_classify_unknowns.run_once('t1', 5, apply=True, prune=False)
    assert stats['picked'] == 0 and stats['skipped_remote'] == 1


def test_classify_one_default_is_qwen_and_never_calls_jev(monkeypatch, tmp_path):
    img = tmp_path / 'frame.png'
    img.write_bytes(b'x')
    monkeypatch.setattr(auto_classify_unknowns, 'classify_open',
                        lambda path, team_id: {'ok': True, 'source': 'qwen',
                                               'label': 'terminal_prompt'})

    def boom(*a, **k):
        raise AssertionError('Jev must not be called in the default path')

    monkeypatch.setattr(auto_classify_unknowns, 'classify_screen', boom)
    out = auto_classify_unknowns.classify_one({'sample_image_path': str(img)}, 't1')
    assert out['label'] == 'terminal_prompt'
    assert 'known_node_id' not in out['dom']
    assert out['dom']['classifier']['source'] == 'qwen'


def test_run_once_default_is_qwen_and_skips_interface_options(monkeypatch):
    row = {'id': 'r1', 'dhash': 'abc', 'scope': 'h1/stb-testop', 'userinterface': 'stb_ui',
           'seen_count': 9, 'sample_image_path': '/tmp/a.png', 'classification_attempts': 0}
    seen = {}
    monkeypatch.setattr(auto_classify_unknowns, 'get_supabase_client', lambda: object())
    monkeypatch.setattr(auto_classify_unknowns, 'pick_candidates', lambda db, t, th: [row])
    monkeypatch.setattr(auto_classify_unknowns, 'local_host_names', lambda: {'h1'})
    monkeypatch.setattr(auto_classify_unknowns, 'interface_options',
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError('options are hybrid-only')))

    def fake_classify(r, team, options=None, mode='qwen'):
        seen.update(mode=mode, options=options)
        return {'dom': {'screen_type': None, 'screen_summary': 'x'},
                'label': 'x', 'ok': True}

    monkeypatch.setattr(auto_classify_unknowns, 'classify_one', fake_classify)
    monkeypatch.setattr(auto_classify_unknowns, 'upsert_proposal', lambda *a: True)
    monkeypatch.setattr(auto_classify_unknowns, 'bump_attempts', lambda *a: None)
    monkeypatch.setattr(auto_classify_unknowns, 'name_row', lambda *a: True)

    stats = auto_classify_unknowns.run_once('t1', 5, apply=True, prune=False)
    assert seen == {'mode': 'qwen', 'options': None}
    assert stats['picked'] == 1 and stats['proposed'] == 1


def test_parse_args_defaults_to_qwen_and_accepts_hybrid():
    assert auto_classify_unknowns.parse_args(['--team-id', 't1']).classifier == 'qwen'
    assert auto_classify_unknowns.parse_args(
        ['--team-id', 't1', '--classifier', 'hybrid']).classifier == 'hybrid'


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))


# --- TASK-159 G4/G6: a name is written once, the closed check runs on the image ---

def test_name_row_goes_through_the_guarded_sql_function():
    fake_db = MagicMock()
    fake_db.rpc.return_value.execute.return_value = types.SimpleNamespace(data=1)
    assert auto_classify_unknowns.name_row(fake_db, 't1', 'r1', 'Splash screen') is True
    assert fake_db.rpc.call_args.args == ('name_screen_row',
                                          {'p_team_id': 't1', 'p_id': 'r1', 'p_label': 'Splash screen'})


def test_name_row_reports_a_refused_rename():
    fake_db = MagicMock()
    fake_db.rpc.return_value.execute.return_value = types.SimpleNamespace(data=0)   # label already a real name
    assert auto_classify_unknowns.name_row(fake_db, 't1', 'r1', 'Other') is False


def test_the_picker_only_offers_unnamed_rows():
    fake_db = MagicMock()
    auto_classify_unknowns.pick_candidates(fake_db, 't1', threshold=5)
    chain = fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value
    chain.is_.assert_called_with('merged_into', 'null')
    assert chain.is_.return_value.or_.call_args.args[0] == 'label.is.null,label.match.^unknown_[0-9]+$'


def test_closed_check_runs_without_an_interface(monkeypatch):
    import shared.src.lib.utils.screen_classifier as sc
    asked = []

    def fake_call(profile, question, path, team_id, max_tokens=16):
        asked.append(question)
        return {'ok': True, 'content': 'SPLASH' if 'splash' in question else 'OTHER'}

    monkeypatch.setattr(sc, '_call', fake_call)
    out = auto_classify_unknowns.classify_state('/tmp/x.jpg', 't1')
    assert out['label'] == 'Splash screen'


def test_state_checks_are_asked_only_of_an_operator_stb(monkeypatch):
    models = {'vpt-pi1/device4': 'stb', 'vpt-pi1/device1': 'android_mobile', 'vpt-mf1/device1': 'apple_tv'}
    monkeypatch.setattr(auto_classify_unknowns, 'device_model_of', lambda scope: models.get(scope, ''))
    assert auto_classify_unknowns.state_hints_for({'scope': 'vpt-pi1/device4'}) == auto_classify_unknowns.STATE_HINTS
    assert auto_classify_unknowns.state_hints_for({'scope': 'vpt-pi1/device1'}) == []
    assert auto_classify_unknowns.state_hints_for({'scope': 'vpt-mf1/device1'}) == []
    assert auto_classify_unknowns.state_hints_for({'scope': 'unknown/device9'}) == []


def test_a_game_frame_is_never_named_a_poster(monkeypatch, tmp_path):
    import shared.src.lib.utils.screen_classifier as sc
    img = tmp_path / 'village.png'
    img.write_bytes(b'x')
    monkeypatch.setattr(auto_classify_unknowns, 'device_model_of', lambda scope: 'android_mobile')

    def no_state_check(*a, **k):
        raise AssertionError('a state check must not be asked of a phone')

    monkeypatch.setattr(sc, '_call', no_state_check)
    monkeypatch.setattr(auto_classify_unknowns, 'classify_open',
                        lambda path, team_id: {'ok': True, 'source': 'qwen', 'label': 'village_base'})
    out = auto_classify_unknowns.classify_one({'sample_image_path': str(img), 'scope': 'vpt-pi1/device1'}, 't1')
    assert out['label'] == 'village_base'


def test_device_model_lookup_reads_the_latest_metrics_row(monkeypatch):
    fake_db = MagicMock()
    chain = fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value
    chain.limit.return_value.execute.return_value = types.SimpleNamespace(data=[{'device_model': 'stb'}])
    monkeypatch.setattr(auto_classify_unknowns, 'get_supabase_client', lambda: fake_db)
    monkeypatch.setattr(auto_classify_unknowns, '_device_models', {})
    assert auto_classify_unknowns.device_model_of('vpt-pi1/device4') == 'stb'
    fake_db.table.assert_called_with('system_device_metrics')
    assert auto_classify_unknowns.device_model_of('') == ''

"""TASK-107 goal 3: the coverage audit row (pure summary) and the MCP tool text."""
import importlib
from datetime import datetime, timezone

import pytest

cov = importlib.import_module('shared.src.lib.database.localize_coverage_db')

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def test_summary_counts_screens_once_and_skips_entry_and_action():
    nodes = [
        {'node_id': 'entry', 'node_type': 'entry'},
        {'node_id': 'press', 'node_type': 'action'},
        {'node_id': 'home', 'node_type': 'screen', 'dhash': 'ab', 'captured_at': '2026-10-05T00:00:00+00:00'},
        {'node_id': 'home', 'node_type': 'screen', 'dhash': None},              # subtree reference row
        {'node_id': 'live', 'label': 'live', 'node_type': 'screen', 'dhash': 'cd',
         'shot_ts': str(int(datetime(2026, 10, 14, tzinfo=timezone.utc).timestamp() * 1000))},
        {'node_id': 'guide', 'label': 'TV Guide', 'node_type': 'menu', 'identity': 'web'},
        {'node_id': 'apps', 'node_type': None, 'updated_at': '2026-09-15T00:00:00Z'},
    ]
    r = cov.summarize({'id': 'u1', 'name': 'stb_tv'}, nodes, corrections=2, now=NOW)
    assert r['screens'] == 4 and r['fingerprinted'] == 2 and r['fingerprinted_pct'] == 50.0
    assert r['identity'] == 1 and r['identity_pct'] == 25.0
    assert r['live_node'] == {'node_id': 'live', 'label': 'live'}
    assert r['fingerprint_age_days'] == {'newest': 1.0, 'median': 10.0, 'oldest': 10.0}
    assert r['missing'] == ['TV Guide', 'apps'] and r['corrections'] == 2


def test_screens_to_fix_gives_each_reason_and_skips_taught_screens():
    nodes = [
        {'node_id': 'ok', 'tree_id': 't1', 'label': 'Ok', 'dhash': 'ab', 'identity': 'web', 'captured_at': '2026-10-10T00:00:00Z'},
        {'node_id': 'new', 'tree_id': 't1', 'label': 'New'},
        {'node_id': 'old', 'tree_id': 't2', 'label': 'Old', 'dhash': 'cd', 'identity': 'web', 'captured_at': '2026-05-01T00:00:00Z'},
        {'node_id': 'noid', 'tree_id': 't1', 'label': 'NoId', 'dhash': 'ef', 'captured_at': '2026-10-14T00:00:00Z'},
    ]
    r = cov.summarize({'id': 'u', 'name': 'shop', 'models': ['web']}, nodes, now=NOW)
    fix = {f['node_id']: f for f in r['screens_to_fix']}
    assert set(fix) == {'new', 'old', 'noid'}
    assert fix['new']['reasons'] == ['no_reference', 'no_identity'] and fix['new']['tree_id'] == 't1'
    assert fix['old']['reasons'] == ['old_reference'] and fix['old']['age_days'] > 90
    assert fix['noid']['reasons'] == ['no_identity']
    assert r['screens_to_fix'][0]['node_id'] == 'new'          # most reasons first


def test_identity_is_not_required_on_a_tv_interface():
    r = cov.summarize({'id': 'u', 'name': 'stb', 'models': ['stb']},
                      [{'node_id': 'home', 'dhash': 'ab', 'captured_at': '2026-10-14T00:00:00Z'}], now=NOW)
    assert r['screens_to_fix'] == []


def test_empty_interface_reads_zero_not_an_error():
    r = cov.summarize({'id': 'u2', 'name': 'labox_tv'}, [{'node_id': 'e', 'node_type': 'entry'}], now=NOW)
    assert r['screens'] == 0 and r['fingerprinted_pct'] == 0.0 and r['live_node'] is None
    assert r['fingerprint_age_days'] is None


def test_fingerprint_time_prefers_its_own_stamp():
    assert cov.fingerprint_time({'captured_at': '2026-10-01T00:00:00Z', 'updated_at': '2026-10-10T00:00:00Z'}).day == 1
    assert cov.fingerprint_time({'shot_ts': '1760000000'}).year == 2025
    assert cov.fingerprint_time({}) is None


def test_mcp_tool_formats_one_line_per_interface(monkeypatch):
    nt = importlib.import_module('backend_server.src.mcp.tools.navigation_tools')

    class Api:
        def get(self, endpoint, params=None):
            assert endpoint == '/server/navigation/localize/coverage' and params['userinterface_name'] == 'stb_tv'
            return {'success': True, 'userinterfaces': [cov.summarize(
                {'id': 'u1', 'name': 'stb_tv'}, [{'node_id': 'home', 'dhash': 'ab', 'captured_at': '2026-10-14T00:00:00Z'}], now=NOW)]}

    tools = nt.NavigationTools.__new__(nt.NavigationTools)
    tools.api = Api()
    out = tools.localize_coverage({'userinterface_name': 'stb_tv', 'team_id': 't'})
    assert out['content'][0]['text'].startswith('stb_tv: 1/1 fingerprinted (100.0%), identity 0.0%, live node none')

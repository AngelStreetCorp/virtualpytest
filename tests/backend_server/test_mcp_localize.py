"""MCP `localize` tool and navigate_to_node starting from the localized node (TASK-104)."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from backend_server.src.mcp.tools import navigation_tools  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"MCP runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


class _Api:
    def __init__(self, verdict):
        self.verdict = verdict
        self.posts = []

    def resolve_userinterface_name(self, name, team_id):
        return 'tree-1', 'ui-1', 'model', None

    def post(self, endpoint, data=None, params=None, timeout=None):
        self.posts.append((endpoint, dict(data or {})))
        if endpoint == '/server/navigation/localize':
            return {'success': True, 'verdict': self.verdict, 'frame_url': 'u'}
        return {'success': True, 'message': 'Already at target'}

    def get(self, endpoint, params=None):
        return {'success': True}


LIVE = {'kind': 'live', 'node_id': 'n-live', 'label': 'live', 'confidence': 1.0, 'evidence': {}}
UNKNOWN = {'kind': 'unknown', 'node_id': None, 'label': 'Unknown', 'confidence': 0.0, 'evidence': {}}
NAV = {'host_name': 'h', 'device_id': 'device1', 'userinterface_name': 'stb_tv',
       'target_node_label': 'home', 'team_id': 't', 'include_screenshot': False}


def _execute_body(api):
    return next(d for e, d in api.posts if e.startswith('/server/navigation/execute/'))


def test_localize_tool_returns_the_verdict():
    api = _Api(LIVE)
    out = navigation_tools.NavigationTools(api).localize(
        {'host_name': 'h', 'device_id': 'device1', 'userinterface_name': 'stb_tv', 'team_id': 't'})
    assert out['verdict'] == LIVE
    assert 'kind=live' in out['content'][0]['text'] and 'node_id=n-live' in out['content'][0]['text']


NODE = {'kind': 'node', 'node_id': 'n-home', 'label': 'home', 'confidence': 0.9, 'evidence': {}}


def test_navigate_starts_from_the_localized_node():
    api = _Api(NODE)
    navigation_tools.NavigationTools(api).navigate_to_node(dict(NAV))
    assert _execute_body(api)['current_node_id'] == 'n-home'


def test_navigate_does_not_start_from_live_motion():
    """A menu over a moving background also reads as live: only a fingerprint match is adopted."""
    api = _Api(LIVE)
    navigation_tools.NavigationTools(api).navigate_to_node(dict(NAV))
    assert 'current_node_id' not in _execute_body(api)


def test_navigate_keeps_old_behaviour_on_unknown():
    api = _Api(UNKNOWN)
    navigation_tools.NavigationTools(api).navigate_to_node(dict(NAV))
    assert 'current_node_id' not in _execute_body(api)


def test_given_position_skips_localize():
    api = _Api(NODE)
    navigation_tools.NavigationTools(api).navigate_to_node({**NAV, 'current_node_id': 'n-tv'})
    assert [e for e, _ in api.posts if e == '/server/navigation/localize'] == []
    assert _execute_body(api)['current_node_id'] == 'n-tv'


def test_no_image_monitor_no_localize(monkeypatch):
    """Owner, 2026-10-14: a device whose profile runs no vpt-monitor-img gets no Localize: the tool refuses
    without calling the host, and navigate_to_node does not localize there."""
    off = 'Localize is off for device1 on h: its monitoring profile does not run the image monitor (vpt-monitor-img)'
    monkeypatch.setattr(navigation_tools.NavigationTools, '_localize_off', staticmethod(lambda h, d: off))
    api = _Api(NODE)
    tools = navigation_tools.NavigationTools(api)
    out = tools.localize({'host_name': 'h', 'device_id': 'device1', 'userinterface_name': 'stb_tv', 'team_id': 't'})
    assert out['isError'] and 'image monitor' in out['content'][0]['text']
    tools.navigate_to_node(dict(NAV))
    assert [e for e, _ in api.posts if e == '/server/navigation/localize'] == []
    assert 'current_node_id' not in _execute_body(api)


def test_localize_off_reads_the_host_monitoring_off_list(monkeypatch):
    from backend_server.src.lib.utils import server_utils

    class _Mgr:
        def get_host(self, name):
            return {'system_stats': {'monitoring_off': ['device3']}}
    monkeypatch.setattr(server_utils, 'get_host_manager', lambda: _Mgr())
    assert navigation_tools.NavigationTools._localize_off('h', 'device3')
    assert navigation_tools.NavigationTools._localize_off('h', 'device4') is None


# ---------------------------------------------------------------- TASK-107 goal 5: localize, not a screenshot

def _nav_auto(api, monkeypatch, **extra):
    shots = []
    monkeypatch.setattr(navigation_tools.NavigationTools, '_attach_screenshot',
                        lambda self, response, *a: shots.append(1) or response['content'].append({'type': 'image'}))
    params = {k: v for k, v in NAV.items() if k != 'include_screenshot'}
    params.update(extra)
    out = navigation_tools.NavigationTools(api).navigate_to_node(params)
    return out, shots


def test_goto_confirmed_by_localize_sends_no_image(monkeypatch):
    out, shots = _nav_auto(_Api(NODE), monkeypatch)                 # target 'home' == verdict label
    assert shots == [] and out['localize']['node_id'] == 'n-home'
    assert 'confirms the target' in out['content'][-1]['text']


def test_goto_landing_elsewhere_reports_it_and_attaches_the_image(monkeypatch):
    other = {**NODE, 'node_id': 'n-guide', 'label': 'tvguide'}
    out, shots = _nav_auto(_Api(other), monkeypatch)
    assert shots == [1] and 'NOT the target (home)' in out['content'][-2]['text']


def test_failed_goto_still_says_where_the_device_is(monkeypatch):
    class _Failing(_Api):
        def post(self, endpoint, data=None, params=None, timeout=None):
            if endpoint.startswith('/server/navigation/execute/'):
                self.posts.append((endpoint, dict(data or {})))
                return {'success': False, 'error': 'edge failed'}
            return super().post(endpoint, data, params, timeout)
    out, shots = _nav_auto(_Failing(NODE), monkeypatch, target_node_label='settings')
    assert out['isError'] and out['localize']['label'] == 'home' and shots == [1]


def test_explicit_true_always_attaches(monkeypatch):
    _, shots = _nav_auto(_Api(NODE), monkeypatch, include_screenshot=True)
    assert shots == [1]

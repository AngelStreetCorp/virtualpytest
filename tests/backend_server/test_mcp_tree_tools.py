"""MCP tree tools: create_node keeps verifications, label is optional, edge writes validate.

Regression guards (2026-10):
- get_device_model_from_userinterface read {success, data} but the route returns the bare
  userinterface dict, so it always failed with "Failed to fetch userinterface: Unknown error".
- create_node's schema had no `verifications` and the payload forwarded only
  label/node_id/node_type/data, so top-level verifications were silently dropped; its
  schema also required `label`, refusing a call that gave only node_id.
- create_edge/update_edge looked the userinterface up at /server/userinterfaces/<id>
  (plural, no such route), so action-set validation was skipped on every edge write.

No server: the API client is a fake that answers by path.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from backend_server.src.mcp.tools.tree_tools import TreeTools, tree_layout  # noqa: E402
    from backend_server.src.mcp.utils.api_client import MCPAPIClient  # noqa: E402
    from backend_server.src.mcp.tool_definitions.auto_generator import generate_tool_definition  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"MCP runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

TEAM = 'team-1'
TREE = 'tree-1'
UI = 'ui-1'
UI_ROW = {'id': UI, 'name': 'sauce-demo', 'models': ['web'], 'root_tree': {'id': TREE}}


class FakeApi:
    """Answers GETs from a {path: response} map and records POSTs."""

    def __init__(self, gets=None):
        self.gets = {
            f'/server/navigationTrees/{TREE}': {'success': True, 'tree': {'id': TREE, 'userinterface_id': UI}},
            f'/server/userinterface/getUserInterface/{UI}': UI_ROW,
        }
        self.gets.update(gets or {})
        self.get_calls = []
        self.posts = []
        self.puts = []

    def get(self, path, params=None):
        self.get_calls.append(path)
        return self.gets.get(path, {'success': False, 'error': 'HTTP 404: not found', 'status_code': 404})

    def post(self, path, data=None, params=None):
        self.posts.append((path, data))
        return {'success': True, 'node': {'node_id': data.get('node_id')}, 'edge': data}

    def put(self, path, data=None, params=None):
        self.puts.append((path, data))
        return {'success': True}

    get_device_model_from_userinterface = MCPAPIClient.get_device_model_from_userinterface

    def resolve_userinterface_name(self, name, team_id):
        return TREE, UI, 'web', None


@pytest.fixture
def tools(monkeypatch):
    api = FakeApi()
    t = TreeTools(api)
    monkeypatch.setattr(t, '_invalidate_host_cache', lambda *a: None)
    t.validated = []

    def fake_validate_verifications(verifications, device_model, *a, **k):
        t.validated.append(('verifications', device_model, verifications))
        bad = [v for v in verifications if v.get('command') == 'notACommand']
        return (not bad), [f"Invalid command 'notACommand'"] if bad else [], []

    def fake_validate_actions(action_sets, device_model, *a, **k):
        t.validated.append(('actions', device_model, action_sets))
        bad = [a for s in action_sets for a in s.get('actions', []) if a.get('command') == 'notACommand']
        return (not bad), [f"Invalid command 'notACommand'"] if bad else [], []

    monkeypatch.setattr(t.verification_validator, 'validate_verifications', fake_validate_verifications)
    monkeypatch.setattr(t.verification_validator, 'get_valid_commands_for_display', lambda m: '')
    monkeypatch.setattr(t.action_validator, 'validate_action_sets', fake_validate_actions)
    monkeypatch.setattr(t.action_validator, 'get_valid_commands_for_display', lambda m: '')
    return t


# ---- 4a: get_device_model_from_userinterface --------------------------------

def test_device_model_from_bare_userinterface_dict():
    api = FakeApi()
    assert MCPAPIClient.get_device_model_from_userinterface(api, UI, TEAM) == ('web', None)


def test_device_model_reports_the_client_error():
    api = FakeApi({f'/server/userinterface/getUserInterface/{UI}':
                   {'success': False, 'error': 'HTTP 404: User interface not found'}})
    model, error = MCPAPIClient.get_device_model_from_userinterface(api, UI, TEAM)
    assert model is None
    assert 'HTTP 404' in error


def test_device_model_without_models_is_unknown():
    api = FakeApi({f'/server/userinterface/getUserInterface/{UI}': {'id': UI, 'models': []}})
    assert MCPAPIClient.get_device_model_from_userinterface(api, UI, TEAM) == ('unknown', None)


# ---- 4b/4c: create_node ------------------------------------------------------

def test_create_node_schema_has_verifications_and_no_required_label():
    schema = generate_tool_definition(TreeTools.create_node, 'create_node')['inputSchema']
    assert schema['properties']['verifications']['type'] == 'array'
    assert 'label' not in schema.get('required', [])


def test_create_node_forwards_top_level_verifications(tools):
    verifications = [{'command': 'waitForElementToAppear', 'verification_type': 'web',
                      'params': {'search_term': '#inventory'}}]
    out = tools.create_node({'tree_id': TREE, 'team_id': TEAM, 'node_id': 'inventory',
                             'label': 'Inventory', 'verifications': verifications})
    assert out['isError'] is False, out
    path, payload = tools.api_client.posts[-1]
    assert path == f'/server/navigationTrees/{TREE}/nodes'
    assert payload['verifications'] == verifications
    assert payload['node_id'] == 'inventory'
    assert payload['label'] == 'Inventory'
    assert 'verifications' not in payload['data']
    # Validated against the model resolved through the (now working) userinterface lookup.
    assert tools.validated == [('verifications', 'web', verifications)]


def test_create_node_lifts_data_verifications(tools):
    verifications = [{'command': 'waitForElementToAppear', 'params': {'search_term': 'x'}}]
    tools.create_node({'tree_id': TREE, 'team_id': TEAM, 'label': 'Cart',
                       'data': {'verifications': verifications, 'note': 'n'}})
    _, payload = tools.api_client.posts[-1]
    assert payload['verifications'] == verifications
    assert payload['data'] == {'note': 'n'}


def test_create_node_rejects_invalid_verifications(tools):
    out = tools.create_node({'tree_id': TREE, 'team_id': TEAM, 'label': 'Cart',
                             'verifications': [{'command': 'notACommand'}]})
    assert out['isError'] is True
    assert tools.api_client.posts == []


@pytest.mark.parametrize('params,expected', [
    ({'node_id': 'home'}, ('home', 'home')),
    ({'data': {'label': 'Home Screen'}}, ('Home Screen', 'Home Screen')),
    ({'label': 'Home Screen'}, ('Home Screen', 'Home Screen')),
    ({'label': 'Home Screen', 'node_id': 'home'}, ('Home Screen', 'home')),
])
def test_create_node_label_defaults(tools, params, expected):
    out = tools.create_node({'tree_id': TREE, 'team_id': TEAM, **params})
    assert out['isError'] is False, out
    _, payload = tools.api_client.posts[-1]
    assert (payload['label'], payload['node_id']) == expected


def test_create_node_needs_some_name(tools):
    out = tools.create_node({'tree_id': TREE, 'team_id': TEAM})
    assert out['isError'] is True
    assert tools.api_client.posts == []


# ---- 4d: edge validation reaches the real userinterface route -----------------

EDGE_ACTIONS = [{'actions': [{'command': 'click_element', 'params': {'element_id': '#go'}}]}]


def test_create_edge_validates_against_the_real_route(tools):
    out = tools.create_edge({'tree_id': TREE, 'team_id': TEAM, 'source_node_id': 'home',
                             'target_node_id': 'cart', 'source_label': 'home',
                             'target_label': 'cart', 'action_sets': EDGE_ACTIONS})
    assert out.get('isError') is not True, out
    assert f'/server/userinterface/getUserInterface/{UI}' in tools.api_client.get_calls
    assert not any('/server/userinterfaces/' in p for p in tools.api_client.get_calls)
    assert tools.validated and tools.validated[0][:2] == ('actions', 'web')


def test_create_edge_rejects_invalid_action(tools):
    out = tools.create_edge({'tree_id': TREE, 'team_id': TEAM, 'source_node_id': 'home',
                             'target_node_id': 'cart', 'source_label': 'home',
                             'target_label': 'cart',
                             'action_sets': [{'actions': [{'command': 'notACommand'}]}]})
    assert out['isError'] is True
    assert tools.api_client.posts == []


def test_update_edge_rejects_invalid_action(tools):
    edge = {'edge_id': 'e1', 'source_node_id': 'home', 'target_node_id': 'cart',
            'action_sets': [{'id': 'home_to_cart', 'actions': [{'command': 'notACommand'}]}]}
    out = tools.update_edge({'tree_id': TREE, 'team_id': TEAM, 'edge': edge})
    assert out['isError'] is True
    assert f'/server/userinterface/getUserInterface/{UI}' in tools.api_client.get_calls
    assert tools.api_client.posts == []


# ---- TASK-135: update_edge endpoint names ------------------------------------

def test_update_edge_reads_react_flow_source_target(tools):
    edge = {'edge_id': 'e1', 'source': 'entry-node', 'target': 'home',
            'action_sets': [{'id': 'entry_to_home', 'actions': [{'command': 'navigate_to_url'}]}]}
    out = tools.update_edge({'tree_id': TREE, 'team_id': TEAM, 'edge': edge})
    assert out['isError'] is False
    (_, sent), = tools.api_client.posts
    assert (sent['source_node_id'], sent['target_node_id']) == ('entry-node', 'home')


def test_update_edge_keeps_stored_endpoints(tools):
    tools.api_client.gets[f'/server/navigationTrees/{TREE}/edges/e1'] = {
        'success': True, 'edge': {'edge_id': 'e1', 'source_node_id': 'entry-node', 'target_node_id': 'home'}}
    edge = {'edge_id': 'e1', 'action_sets': [{'id': 's1', 'actions': [{'command': 'navigate_to_url'}]}]}
    out = tools.update_edge({'tree_id': TREE, 'team_id': TEAM, 'edge': edge})
    assert out['isError'] is False
    (_, sent), = tools.api_client.posts
    assert (sent['source_node_id'], sent['target_node_id']) == ('entry-node', 'home')


def test_update_edge_without_any_endpoint_is_refused(tools):
    edge = {'edge_id': 'missing', 'action_sets': [{'id': 's1', 'actions': [{'command': 'navigate_to_url'}]}]}
    out = tools.update_edge({'tree_id': TREE, 'team_id': TEAM, 'edge': edge})
    assert out['isError'] is True
    assert tools.api_client.posts == []


# ---- update_node keeps stored position / data; auto_layout_tree (TASK-135) --------

def test_update_node_keeps_stored_position_and_screenshot(tools):
    tools.api_client.gets[f'/server/navigationTrees/{TREE}/nodes/vod'] = {'success': True, 'node': {
        'node_id': 'vod', 'label': 'vod', 'position_x': 900, 'position_y': 440,
        'data': {'screenshot': 'https://r2/vod.jpg', 'fingerprint': {'dhash': 'ab'}}}}
    out = tools.update_node({'tree_id': TREE, 'team_id': TEAM,
                             'node': {'node_id': 'vod', 'label': 'VOD', 'data': {'type': 'screen'}}})
    assert out['isError'] is False
    (_, sent), = tools.api_client.posts
    assert (sent['position_x'], sent['position_y']) == (900, 440)
    assert sent['data'] == {'screenshot': 'https://r2/vod.jpg', 'fingerprint': {'dhash': 'ab'}, 'type': 'screen'}
    assert sent['label'] == 'VOD'


def test_update_node_given_position_wins(tools):
    node = {'node_id': 'n', 'label': 'n', 'position_x': 5, 'position_y': 6, 'data': {'screenshot': 's'}}
    tools.update_node({'tree_id': TREE, 'team_id': TEAM, 'node': node})
    (_, sent), = tools.api_client.posts
    assert (sent['position_x'], sent['position_y']) == (5, 6)
    assert f'/server/navigationTrees/{TREE}/nodes/n' not in tools.api_client.get_calls


def test_tree_layout_rows_and_centring():
    ids = ['home', 'entry-node', 'a', 'b', 'a1', 'a2']
    edges = [('entry-node', 'home'), ('home', 'a'), ('home', 'b'), ('a', 'a1'), ('a', 'a2'), ('a1', 'home')]
    pos = tree_layout(ids, edges)
    assert pos['entry-node'][1] == 0 and pos['home'][1] == 220 and pos['a'][1] == 440 and pos['a1'][1] == 660
    assert pos['a'][0] == (pos['a1'][0] + pos['a2'][0]) / 2
    assert len({p for p in pos.values()}) == len(ids)  # nothing stacked


def test_tree_layout_cycle_only_nodes_are_placed():
    pos = tree_layout(['x', 'y'], [('x', 'y'), ('y', 'x')])
    assert set(pos) == {'x', 'y'} and pos['x'] != pos['y']


def test_auto_layout_tree_moves_stacked_nodes_only(tools):
    tools.api_client.gets[f'/server/navigationTrees/{TREE}/full'] = {'success': True, 'nodes': [
        {'node_id': 'entry-node', 'position_x': 0, 'position_y': 0, 'id': 'u1', 'tree_id': TREE, 'has_subtree': False},
        {'node_id': 'home', 'position_x': 0, 'position_y': 0, 'data': {'screenshot': 's'}, 'verifications': [{'c': 1}]},
    ], 'edges': [{'source_node_id': 'entry-node', 'target_node_id': 'home'}]}
    out = tools.auto_layout_tree({'tree_id': TREE, 'team_id': TEAM})
    assert out['isError'] is False and '1 moved' in out['content'][0]['text']
    (path, body), = tools.api_client.puts
    assert path.endswith('/nodes/home') and body['position_y'] == 220
    assert body['data'] == {'screenshot': 's'} and body['verifications'] == [{'c': 1}]

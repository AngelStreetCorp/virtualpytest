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
    from backend_server.src.mcp.tools.tree_tools import TreeTools  # noqa: E402
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

    def get(self, path, params=None):
        self.get_calls.append(path)
        return self.gets.get(path, {'success': False, 'error': 'HTTP 404: not found', 'status_code': 404})

    def post(self, path, data=None, params=None):
        self.posts.append((path, data))
        return {'success': True, 'node': {'node_id': data.get('node_id')}, 'edge': data}

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

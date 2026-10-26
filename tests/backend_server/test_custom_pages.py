"""Custom pages (TASK-139): catalogue rules, per-block permissions, ownership, drafts and sharing."""

import os
import sys

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.backend_server import _task42_services_common as common  # noqa: E402
from backend_server.src.routes.server_custom_pages_routes import server_custom_pages_bp  # noqa: E402
from backend_server.src.services.custom_pages import catalogue, service  # noqa: E402
from backend_server.src.services.custom_pages.catalogue import DefinitionError  # noqa: E402

pytestmark = pytest.mark.unit

BASE = ['pages.custom:view', 'pages.custom:edit', 'device_control:view', 'device_control:execute', 'reports.tests:view']
EXAMPLE = {'blocks': [{'type': 'device_picker', 'settings': {'model_filter': 'stb'}}, {'type': 'node_goto'},
                      {'type': 'localize_result'}]}


def client_for(monkeypatch, fake=None, user=common.USER_A, permissions=BASE):
    fake = fake or common.install(monkeypatch)
    from shared.src.lib.database import custom_pages_db
    monkeypatch.setattr(custom_pages_db, 'get_supabase', lambda: fake)
    return fake, common.make_app(server_custom_pages_bp, user_id=user, permissions=permissions).test_client()


def create(client, **extra):
    body = {'team_id': common.TEAM_A, 'title': 'STB navigator', 'definition': EXAMPLE, **extra}
    return client.post('/server/custom-pages', json=body)


# ---- catalogue / definition rules

def test_definition_is_canonicalised_and_auto_wired():
    d = catalogue.normalize_definition(EXAMPLE)
    assert [b['id'] for b in d['blocks']] == ['b1', 'b2', 'b3']
    assert d['blocks'][1]['settings']['device_from'] == 'b1'
    assert all(b['x'] + b['w'] <= catalogue.GRID_COLUMNS for b in d['blocks'])


@pytest.mark.parametrize('blocks, fragment', [
    ([{'type': 'iframe'}], 'unknown block type'),
    ([{'type': 'text', 'settings': {'html': '<b>'}}], 'unknown setting'),
    ([{'type': 'device_picker', 'settings': {'model_filter': 'toaster'}}], 'must be one of'),
    ([{'type': 'node_goto'}], 'needs a device_picker'),
    ([{'type': 'text', 'w': 9}], 'w must be'),
    ([{'type': 'report', 'settings': {'report_id': 'nope'}}], 'must be an id'),
    ([{'type': 'text', 'id': 'a'}, {'type': 'text', 'id': 'a'}], 'used twice'),
])
def test_bad_definitions_are_refused_with_a_reason(blocks, fragment):
    with pytest.raises(DefinitionError, match=fragment):
        catalogue.normalize_definition({'blocks': blocks})


def test_ops_edit_and_removing_the_picker_is_refused_for_its_readers():
    d = catalogue.normalize_definition(EXAMPLE)
    edited = catalogue.apply_ops(d, [{'op': 'remove_block', 'id': 'b3'}, {'op': 'add_block', 'type': 'recent_runs'}])
    assert [b['type'] for b in catalogue.normalize_definition(edited)['blocks']] == ['device_picker', 'node_goto', 'recent_runs']
    with pytest.raises(DefinitionError, match='needs a device_picker'):
        catalogue.normalize_definition(catalogue.apply_ops(d, [{'op': 'remove_block', 'id': 'b1'}]))
    with pytest.raises(DefinitionError, match='no block with id'):
        catalogue.apply_ops(d, [{'op': 'remove_block', 'id': 'zz'}])


def test_catalogue_lists_locked_blocks_with_the_reason():
    held = {'device_control:view'}
    cat = catalogue.catalogue_for(lambda p: p in held)
    names = {b['type'] for b in cat['available']}
    assert {'device_picker', 'stream', 'text'} <= names and 'node_goto' not in names
    locked = {b['type']: b for b in cat['unavailable']}
    assert 'device_control:execute' in locked['node_goto']['reason']


def test_only_new_or_changed_blocks_need_the_permission():
    d = catalogue.normalize_definition(EXAMPLE)
    no_exec = lambda p: p != 'device_control:execute'  # noqa: E731
    with pytest.raises(DefinitionError) as e:
        catalogue.normalize_definition(d, holds=no_exec)
    assert e.value.status == 403 and e.value.extra['missing'] == ['device_control:execute']
    assert catalogue.normalize_definition(d, previous=d, holds=no_exec) == d


# ---- routes

def test_create_get_list_roundtrip_and_team_scope(monkeypatch):
    fake, client = client_for(monkeypatch)
    resp = create(client)
    assert resp.status_code == 201
    page = resp.get_json()
    assert page['access'] == 'owner' and page['status'] == 'saved' and page['visibility'] == 'private'
    assert all(s['available'] for s in page['block_states'].values())
    stored = fake.tables['custom_pages'][0]
    assert stored['team_id'] == common.TEAM_A and stored['owner_id'] == common.USER_A
    items = client.get('/server/custom-pages', query_string={'team_id': common.TEAM_A}).get_json()['items']
    assert [i['id'] for i in items] == [page['id']] and 'definition' not in items[0]
    assert client.get(f"/server/custom-pages/{page['id']}", query_string={'team_id': common.TEAM_B}).status_code == 404


def test_block_without_its_permission_is_refused_at_save(monkeypatch):
    _, client = client_for(monkeypatch, permissions=['pages.custom:view', 'pages.custom:edit', 'device_control:view'])
    resp = create(client)
    assert resp.status_code == 403
    body = resp.get_json()
    assert body['block_type'] == 'node_goto' and body['missing'] == ['device_control:execute']


def test_viewer_without_edit_permission_cannot_create(monkeypatch):
    _, client = client_for(monkeypatch, permissions=['pages.custom:view'])
    assert create(client).status_code == 403
    assert client.get('/server/custom-pages', query_string={'team_id': common.TEAM_A}).status_code == 200


def test_other_user_sees_nothing_until_shared_and_drafts_stay_private(monkeypatch):
    fake, owner = client_for(monkeypatch)
    page_id = create(owner).get_json()['id']
    draft_id = create(owner, status='draft', title='Draft').get_json()['id']
    _, other = client_for(monkeypatch, fake=fake, user=common.USER_B)
    q = {'team_id': common.TEAM_A}
    assert other.get('/server/custom-pages', query_string=q).get_json()['items'] == []
    assert other.get(f'/server/custom-pages/{page_id}', query_string=q).status_code == 404

    members = [{'user_id': common.USER_B, 'full_name': 'Bea', 'email': 'b@x', 'role': 'tester'}]
    monkeypatch.setattr(service.teams_db, 'get_team_members', lambda team_id: members)
    monkeypatch.setattr(service, 'holds_for_user', lambda uid: (lambda p: p == 'device_control:view'))
    resp = owner.put(f'/server/custom-pages/{page_id}/sharing',
                     json={'team_id': common.TEAM_A, 'visibility': 'private',
                           'shares': [{'user_id': common.USER_B, 'can_edit': False}]})
    assert resp.status_code == 200
    bea = resp.get_json()['members'][0]
    assert bea['shared'] is True and bea['locked_blocks'] == 2  # node_goto + localize need execute

    seen = other.get(f'/server/custom-pages/{page_id}', query_string=q)
    assert seen.status_code == 200 and seen.get_json()['access'] == 'view'
    # a view-only share cannot change the page, a draft is never reachable
    assert other.patch(f'/server/custom-pages/{page_id}', json={**q, 'title': 'x'}).status_code == 403
    assert other.get(f'/server/custom-pages/{draft_id}', query_string=q).status_code == 404
    assert other.delete(f'/server/custom-pages/{page_id}', query_string=q).status_code == 404


def test_team_visibility_and_edit_share(monkeypatch):
    fake, owner = client_for(monkeypatch)
    page_id = create(owner).get_json()['id']
    members = [{'user_id': common.USER_B, 'full_name': 'Bea', 'role': 'tester'}]
    monkeypatch.setattr(service.teams_db, 'get_team_members', lambda team_id: members)
    monkeypatch.setattr(service, 'holds_for_user', lambda uid: (lambda p: True))
    owner.put(f'/server/custom-pages/{page_id}/sharing',
              json={'team_id': common.TEAM_A, 'visibility': 'team', 'shares': [{'user_id': common.USER_B, 'can_edit': True}]})
    _, other = client_for(monkeypatch, fake=fake, user=common.USER_B)
    q = {'team_id': common.TEAM_A}
    assert [i['id'] for i in other.get('/server/custom-pages', query_string=q).get_json()['items']] == [page_id]
    patched = other.patch(f'/server/custom-pages/{page_id}',
                          json={**q, 'ops': [{'op': 'add_block', 'type': 'text', 'settings': {'text': 'hi'}}]})
    assert patched.status_code == 200 and patched.get_json()['block_count'] == 4
    # only the owner shares, saves or deletes
    assert other.get(f'/server/custom-pages/{page_id}/sharing', query_string=q).status_code == 404
    assert other.patch(f'/server/custom-pages/{page_id}', json={**q, 'status': 'draft'}).status_code == 403


def test_sharing_a_non_member_or_a_draft_is_refused(monkeypatch):
    _, owner = client_for(monkeypatch)
    draft_id = create(owner, status='draft').get_json()['id']
    monkeypatch.setattr(service.teams_db, 'get_team_members', lambda team_id: [])
    r = owner.put(f'/server/custom-pages/{draft_id}/sharing', json={'team_id': common.TEAM_A, 'visibility': 'team', 'shares': []})
    assert r.status_code == 400 and 'save the page' in r.get_json()['error']
    page_id = create(owner).get_json()['id']
    r = owner.put(f'/server/custom-pages/{page_id}/sharing',
                  json={'team_id': common.TEAM_A, 'visibility': 'private', 'shares': [{'user_id': 'stranger'}]})
    assert r.status_code == 400 and 'not a member' in r.get_json()['error']


def test_patch_revalidates_and_save_promotes_a_draft(monkeypatch):
    _, client = client_for(monkeypatch)
    page_id = create(client, status='draft').get_json()['id']
    q = {'team_id': common.TEAM_A}
    assert client.patch(f'/server/custom-pages/{page_id}', json={**q, 'definition': {'blocks': [{'type': 'nope'}]}}).status_code == 400
    saved = client.patch(f'/server/custom-pages/{page_id}', json={**q, 'status': 'saved', 'title': 'Renamed'})
    assert saved.get_json()['status'] == 'saved' and saved.get_json()['title'] == 'Renamed'
    assert client.delete(f'/server/custom-pages/{page_id}', query_string=q).status_code == 200
    assert client.get(f'/server/custom-pages/{page_id}', query_string=q).status_code == 404


def test_catalogue_route_separates_locked_blocks(monkeypatch):
    _, client = client_for(monkeypatch, permissions=['pages.custom:view', 'device_control:view'])
    body = client.get('/server/custom-pages/catalogue', query_string={'team_id': common.TEAM_A}).get_json()
    assert 'node_goto' in {b['type'] for b in body['unavailable']}
    assert 'stream' in {b['type'] for b in body['available']}


# ---- Atlas tools

def tool_params(**extra):
    return {'_context_team_id': common.TEAM_A, '_context_user_id': common.USER_A, '_context_user_role': 'tester', **extra}


def tools_for(monkeypatch, held):
    from backend_server.src.mcp.tools import custom_page_tools
    fake = common.install(monkeypatch)
    from shared.src.lib.database import custom_pages_db
    monkeypatch.setattr(custom_pages_db, 'get_supabase', lambda: fake)
    monkeypatch.setattr(service, 'holds_for_user', lambda uid: (lambda p: p in held))
    return fake, custom_page_tools.CustomPageTools()


def test_tool_builds_a_draft_from_catalogue_blocks(monkeypatch):
    fake, tools = tools_for(monkeypatch, set(BASE))
    result = tools.create_custom_page(tool_params(title='STB navigator', blocks=EXAMPLE['blocks']))
    assert result['isError'] is False and result['url'].startswith('/pages/')
    assert fake.tables['custom_pages'][0]['status'] == 'draft'
    page_id = result['page']['id']
    edited = tools.update_custom_page(tool_params(page_id=page_id, ops=[{'op': 'remove_block', 'id': 'b3'}]))
    assert edited['page']['block_count'] == 2


def test_tool_refuses_a_block_the_user_may_not_use_and_says_which(monkeypatch):
    _, tools = tools_for(monkeypatch, {'pages.custom:view', 'pages.custom:edit', 'device_control:view'})
    result = tools.create_custom_page(tool_params(title='x', blocks=EXAMPLE['blocks']))
    assert result['isError'] is True
    assert 'device_control:execute' in result['content'][0]['text']
    listing = tools.list_custom_blocks(tool_params())
    assert any(b['type'] == 'node_goto' for b in listing['catalogue']['unavailable'])
    assert 'NOT use' in listing['content'][0]['text']


def test_tool_needs_the_edit_permission_and_a_known_user(monkeypatch):
    _, tools = tools_for(monkeypatch, {'pages.custom:view'})
    assert tools.create_custom_page(tool_params(title='x', blocks=[]))['isError'] is True
    assert tools.list_custom_pages(tool_params())['isError'] is False
    from backend_server.src.mcp.tools.custom_page_tools import CustomPageTools
    monkeypatch.setattr(service, 'holds_for_user', lambda uid: None)
    assert CustomPageTools().list_custom_pages(tool_params())['isError'] is True


def test_tool_treats_an_unknown_admin_principal_as_admin(monkeypatch):
    from backend_server.src.mcp.tools.custom_page_tools import CustomPageTools
    fake = common.install(monkeypatch)
    from shared.src.lib.database import custom_pages_db
    monkeypatch.setattr(custom_pages_db, 'get_supabase', lambda: fake)
    monkeypatch.setattr(service, 'holds_for_user', lambda uid: None)
    admin = CustomPageTools().create_custom_page(tool_params(_context_user_role='admin', title='x', blocks=EXAMPLE['blocks']))
    assert admin['isError'] is False
    assert CustomPageTools().create_custom_page(tool_params(_context_user_role='tester', title='x', blocks=[]))['isError'] is True

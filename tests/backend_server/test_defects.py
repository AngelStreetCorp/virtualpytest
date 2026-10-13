"""Defects, evidence links and the explicit Jira push/refresh (TASK-42 §4.3, §9 Defects/Jira).

The Jira side is a controlled stub injected into ``JiraClient`` — no network.
The push state machine RPCs are emulated by a small in-memory model that
mirrors ``rm_claim_defect_jira_push`` / complete / fail (verified for real in
``test_run_services_pg.py``).
"""

import os
import sys
import urllib.parse
from datetime import datetime, timezone

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.backend_server import _task42_services_common as common  # noqa: E402
from tests.backend_server import _task42_common as core  # noqa: E402
from backend_server.src.routes.server_defects_routes import server_defects_bp  # noqa: E402
from backend_server.src.services.defects import jira  # noqa: E402

pytestmark = pytest.mark.unit

PERMS = ['reports.tests:view', 'reports.defects:edit']


class PushModel:
    """In-memory equivalent of the defect_jira_pushes state machine."""

    def __init__(self, fake):
        self.fake = fake
        self.rows = {}
        self.leased = set()
        fake.rpc_handlers.update({
            'rm_claim_defect_jira_push': self.claim,
            'rm_complete_defect_jira_push': self.complete,
            'rm_fail_defect_jira_push': self.fail,
        })

    def claim(self, p):
        key = (p['p_team_id'], p['p_defect_id'])
        if not any(d['id'] == p['p_defect_id'] and d['team_id'] == p['p_team_id']
                   for d in self.fake.tables.get('defects', [])):
            return {'claimed': False, 'reason': 'not_found'}
        row = self.rows.setdefault(key, {'state': 'pending', 'attempts': 0, 'instance_id': p['p_instance_id'],
                                         'project_key': p['p_project_key'],
                                         'correlation_label': f"vpt-defect-{p['p_defect_id']}"})
        if row['state'] == 'created':
            return {'claimed': False, 'reason': 'already_created', 'external_key': row['external_key'],
                    'external_url': row['external_url']}
        if key in self.leased:
            return {'claimed': False, 'reason': 'in_flight'}
        reconcile = row['attempts'] > 0
        row['attempts'] += 1
        self.leased.add(key)
        return {'claimed': True, 'attempt': row['attempts'], 'reconcile': reconcile,
                'correlation_label': row['correlation_label']}

    def complete(self, p):
        key = (p['p_team_id'], p['p_defect_id'])
        self.rows[key].update(state='created', external_key=p['p_external_key'], external_url=p['p_external_url'])
        self.leased.discard(key)
        for d in self.fake.tables['defects']:
            if d['id'] == p['p_defect_id']:
                d.update(integration='jira', external_key=p['p_external_key'], external_url=p['p_external_url'])
        return True

    def fail(self, p):
        key = (p['p_team_id'], p['p_defect_id'])
        self.rows[key]['state'] = 'failed'
        if p['p_release_lease']:
            self.leased.discard(key)
        return True


class StubJira:
    def __init__(self):
        self.issues = []
        self.creates = 0
        self.fail_next_create_after_sending = False
        self.searches = 0

    def __call__(self, domain, endpoint, email, token, method='GET', data=None):
        if method == 'POST' and endpoint == '/issue':
            self.creates += 1
            key = f'QA-{len(self.issues) + 1}'
            self.issues.append({'key': key, 'fields': {'labels': data['fields']['labels'],
                                                       'project': {'key': data['fields']['project']['key']}}})
            if self.fail_next_create_after_sending:
                self.fail_next_create_after_sending = False
                raise TimeoutError('read timed out')  # created on Jira, response lost
            return {'key': key}
        if endpoint.startswith('/search/jql'):
            self.searches += 1
            jql = urllib.parse.unquote(endpoint)
            return {'issues': [i for i in self.issues if f'labels = "{i["fields"]["labels"][0]}"' in jql]}
        raise AssertionError(endpoint)


@pytest.fixture
def env(monkeypatch):
    fake = common.install(monkeypatch)
    fake.tables['script_results'] = []
    stub = StubJira()
    instance = jira.JiraInstance(id='jira-1', domain='example.atlassian.net', email='bot@example.com',
                                 api_token='secret', project_key='QA')
    import backend_server.src.routes.server_integrations_routes as integrations
    monkeypatch.setattr(integrations, 'load_jira_instances', lambda: [
        {'id': 'jira-1', 'name': 'QA', 'domain': instance.domain, 'email': instance.email,
         'apiToken': instance.api_token, 'projectKey': 'QA', 'teamIds': [common.TEAM_A]},
        {'id': 'jira-other', 'name': 'Other team', 'domain': 'other.atlassian.net', 'email': 'x@example.com',
         'apiToken': 'other-secret', 'projectKey': 'OPS', 'teamIds': [common.TEAM_B]},
    ])
    monkeypatch.setattr(jira, '_default_api_caller', lambda: stub)
    import shared.src.lib.database.run_defects_db as ddb
    monkeypatch.setattr(ddb, 'list_evidence', lambda *a, **k: {'items': [], 'total': 2})
    client = common.make_app(server_defects_bp, permissions=PERMS).test_client()
    return fake, client, stub


def _create(client, **extra):
    resp = client.post('/server/defects', json={'team_id': common.TEAM_A, 'title': 'Black screen on zap', **extra})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def test_one_defect_links_multiple_failed_attempts_in_scope(env):
    fake, client, _ = env
    a, b = common.script_result(success=False), common.script_result(success=False, device='device2')
    fake.tables['script_results'] += [a, b]
    defect = _create(client, script_result_ids=[a['id'], b['id']])
    links = fake.tables['defect_script_results']
    assert {l['script_result_id'] for l in links} == {a['id'], b['id']}
    assert all(l['team_id'] == common.TEAM_A and l['defect_id'] == defect['id'] for l in links)
    assert defect['integration'] == 'local' and defect['status'] == 'open'


def test_evidence_outside_scope_or_team_is_rejected(env):
    fake, client, _ = env
    other_team = common.script_result(team_id=common.TEAM_B)
    other_server = common.script_result(host='host-on-another-server')
    fake.tables['script_results'] += [other_team, other_server]
    resp = client.post('/server/defects', json={'team_id': common.TEAM_A, 'title': 'x',
                                                'script_result_ids': [other_team['id'], other_server['id']]})
    assert resp.status_code == 404
    assert set(resp.get_json()['script_result_ids']) == {other_team['id'], other_server['id']}
    assert 'defects' not in fake.tables or fake.tables['defects'] == []


def test_resolving_never_touches_script_results(env):
    fake, client, _ = env
    result = common.script_result(success=False, discard=False)
    fake.tables['script_results'].append(result)
    before = dict(result)
    defect = _create(client, script_result_ids=[result['id']])
    resp = client.patch(f"/server/defects/{defect['id']}", json={'team_id': common.TEAM_A, 'status': 'resolved'})
    assert resp.status_code == 200 and resp.get_json()['status'] == 'resolved'
    assert fake.tables['script_results'][0] == before


def test_patch_rejects_external_fields_and_bad_values(env):
    _, client, _ = env
    defect = _create(client)
    url = f"/server/defects/{defect['id']}"
    assert client.patch(url, json={'team_id': common.TEAM_A, 'external_key': 'QA-1'}).status_code == 400
    assert client.patch(url, json={'team_id': common.TEAM_A, 'status': 'wont_fix'}).status_code == 400
    assert client.patch(url, json={'team_id': common.TEAM_A, 'title': ' '}).status_code == 400


def test_cross_team_defect_is_not_found(env):
    _, client, _ = env
    defect = _create(client)
    assert client.get(f"/server/defects/{defect['id']}", query_string={'team_id': common.TEAM_B}).status_code == 404
    assert client.patch(f"/server/defects/{defect['id']}", json={'team_id': common.TEAM_B, 'status': 'closed'}).status_code == 404


def test_push_creates_once_and_retry_is_idempotent(env):
    fake, client, stub = env
    PushModel(fake)
    defect = _create(client)
    first = client.post(f"/server/defects/{defect['id']}/push-jira", json={'team_id': common.TEAM_A})
    assert first.status_code == 201
    assert first.get_json()['external_key'] == 'QA-1'
    second = client.post(f"/server/defects/{defect['id']}/push-jira", json={'team_id': common.TEAM_A})
    assert second.status_code == 200 and second.get_json()['idempotent'] is True
    assert stub.creates == 1
    stored = next(d for d in fake.tables['defects'] if d['id'] == defect['id'])
    assert stored['integration'] == 'jira' and stored['external_key'] == 'QA-1'


def test_retry_after_timeout_reconciles_instead_of_creating_a_second_issue(env):
    fake, client, stub = env
    model = PushModel(fake)
    defect = _create(client)
    stub.fail_next_create_after_sending = True
    lost = client.post(f"/server/defects/{defect['id']}/push-jira", json={'team_id': common.TEAM_A})
    assert lost.status_code == 504 and lost.get_json()['state'] == 'unknown'
    # Lease kept on an unknown outcome: an immediate retry is refused, not re-sent.
    blocked = client.post(f"/server/defects/{defect['id']}/push-jira", json={'team_id': common.TEAM_A})
    assert blocked.status_code == 409
    assert stub.creates == 1
    model.leased.clear()  # lease expired
    retry = client.post(f"/server/defects/{defect['id']}/push-jira", json={'team_id': common.TEAM_A})
    assert retry.status_code == 201
    assert retry.get_json()['external_key'] == 'QA-1' and retry.get_json()['idempotent'] is True
    assert stub.creates == 1 and stub.searches == 1


def test_push_requires_a_configured_instance(env):
    _, client, _ = env
    defect = _create(client)
    resp = client.post(f"/server/defects/{defect['id']}/push-jira", json={'team_id': common.TEAM_A, 'instance_id': 'nope'})
    assert resp.status_code == 409


def test_push_refuses_an_instance_not_enabled_for_the_team(env):
    _, client, stub = env
    defect = _create(client)
    resp = client.post(f"/server/defects/{defect['id']}/push-jira",
                       json={'team_id': common.TEAM_A, 'instance_id': 'jira-other'})
    assert resp.status_code == 403 and 'not enabled for this team' in resp.get_json()['error']
    assert stub.creates == 0


def test_push_never_auto_picks_an_instance_of_another_team(env, monkeypatch):
    _, client, stub = env
    import backend_server.src.routes.server_integrations_routes as integrations
    # the only configured instance belongs to another team
    monkeypatch.setattr(integrations, 'load_jira_instances', lambda: [
        {'id': 'jira-other', 'name': 'Other', 'domain': 'other.atlassian.net', 'email': 'x@example.com',
         'apiToken': 's', 'projectKey': 'OPS', 'teamIds': [common.TEAM_B]}])
    defect = _create(client)
    resp = client.post(f"/server/defects/{defect['id']}/push-jira", json={'team_id': common.TEAM_A})
    assert resp.status_code == 409 and 'no Jira instance is enabled' in resp.get_json()['error']
    assert stub.creates == 0


@pytest.mark.parametrize('instances,instance_id,status', [
    ([{'id': 'j', 'domain': 'd', 'email': 'e', 'apiToken': 't', 'projectKey': 'P'}], None, 409),   # no teamIds
    ([{'id': 'j', 'domain': 'd', 'email': 'e', 'apiToken': 't', 'projectKey': 'P', 'teamIds': []}], 'j', 403),
    ([{'id': 'j1', 'domain': 'd', 'email': 'e', 'apiToken': 't', 'projectKey': 'P', 'teamIds': [common.TEAM_A]},
      {'id': 'j2', 'domain': 'd', 'email': 'e', 'apiToken': 't', 'projectKey': 'P', 'teamIds': [common.TEAM_A]}],
     None, 409),                                                                                    # ambiguous
    ([{'id': 'j', 'domain': 'd', 'email': 'e', 'apiToken': 't', 'projectKey': '', 'teamIds': [common.TEAM_A]}],
     None, 409),                                                                                    # no project
])
def test_load_instance_requires_an_explicit_team_allowlist(monkeypatch, instances, instance_id, status):
    import backend_server.src.routes.server_integrations_routes as integrations
    monkeypatch.setattr(integrations, 'load_jira_instances', lambda: instances)
    with pytest.raises(jira.JiraNotAvailable) as exc:
        jira.load_instance(instance_id, common.TEAM_A)
    assert exc.value.status == status


def test_load_instance_picks_the_single_allowed_instance(monkeypatch):
    import backend_server.src.routes.server_integrations_routes as integrations
    monkeypatch.setattr(integrations, 'load_jira_instances', lambda: [
        {'id': 'b', 'domain': 'b', 'email': 'e', 'apiToken': 't', 'projectKey': 'B', 'teamIds': [common.TEAM_B]},
        {'id': 'a', 'domain': 'a', 'email': 'e', 'apiToken': 't', 'projectKey': 'A', 'teamIds': [common.TEAM_A]}])
    assert jira.load_instance(None, common.TEAM_A).id == 'a'
    assert jira.load_instance(None, common.TEAM_B).id == 'b'


def _linked_defect(fake, client):
    PushModel(fake)
    defect = _create(client)
    client.post(f"/server/defects/{defect['id']}/push-jira", json={'team_id': common.TEAM_A})
    fake.tables['defect_jira_pushes'] = [{'team_id': common.TEAM_A, 'defect_id': defect['id'], 'instance_id': 'jira-1',
                                          'project_key': 'QA', 'state': 'created', 'external_key': 'QA-1'}]
    return defect


def _issue(category, updated, key='QA-1', project='QA'):
    return {'key': key, 'fields': {'project': {'key': project}, 'updated': updated,
                                   'status': {'name': 'Done', 'statusCategory': {'key': category}}}}


def test_refresh_maps_status_category_and_updates_only_this_defect(env, monkeypatch):
    fake, client, _ = env
    defect = _linked_defect(fake, client)
    other = _create(client, title='unrelated')
    monkeypatch.setattr(jira.JiraClient, 'get_issue', lambda self, key: _issue('done', '2026-10-03T08:15:30.123+0000'))
    resp = client.post(f"/server/defects/{defect['id']}/refresh-jira", json={'team_id': common.TEAM_A})
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'resolved'
    assert resp.get_json()['external_updated_at'] == '2026-10-03T08:15:30.123000Z'
    assert any('external_updated_at.lt.2026-10-03T08:15:30.123000Z' in e for e in fake.or_expressions)
    assert next(d for d in fake.tables['defects'] if d['id'] == other['id'])['status'] == 'open'


@pytest.mark.parametrize('issue,status', [
    (_issue('done', '2026-10-03T08:00:00.000+0000', key='QA-9'), 409),       # wrong issue
    (_issue('done', '2026-10-03T08:00:00.000+0000', project='OPS'), 409),    # wrong project
    (_issue('weird', '2026-10-03T08:00:00.000+0000'), 422),                  # not in allowlist
    (_issue('done', None), 422),                                             # no timestamp
])
def test_refresh_validates_mapping(env, monkeypatch, issue, status):
    fake, client, _ = env
    defect = _linked_defect(fake, client)
    monkeypatch.setattr(jira.JiraClient, 'get_issue', lambda self, key: issue)
    assert client.post(f"/server/defects/{defect['id']}/refresh-jira", json={'team_id': common.TEAM_A}).status_code == status


def test_refresh_of_local_defect_is_refused(env):
    _, client, _ = env
    defect = _create(client)
    assert client.post(f"/server/defects/{defect['id']}/refresh-jira", json={'team_id': common.TEAM_A}).status_code == 409


def test_write_permission_required(monkeypatch):
    common.install(monkeypatch)
    client = common.make_app(server_defects_bp, permissions=['reports.tests:view']).test_client()
    assert client.post('/server/defects', json={'team_id': common.TEAM_A, 'title': 'x'}).status_code == 403
    assert client.get('/server/defects', query_string={'team_id': common.TEAM_A}).status_code == 200


def test_jira_time_parsing():
    parsed = jira._parse_jira_time('2026-10-03T08:15:30.123+0200')
    assert parsed == datetime(2026, 10, 3, 6, 15, 30, 123000, tzinfo=timezone.utc)
    assert jira._parse_jira_time('garbage') is None


def test_refresh_refused_once_the_team_is_removed_from_the_instance(env, monkeypatch):
    fake, client, _ = env
    defect = _linked_defect(fake, client)
    import backend_server.src.routes.server_integrations_routes as integrations
    monkeypatch.setattr(integrations, 'load_jira_instances', lambda: [
        {'id': 'jira-1', 'domain': 'example.atlassian.net', 'email': 'bot@example.com', 'apiToken': 's',
         'projectKey': 'QA', 'teamIds': [common.TEAM_B]}])
    called = []
    monkeypatch.setattr(jira.JiraClient, 'get_issue', lambda self, key: called.append(key) or {})
    resp = client.post(f"/server/defects/{defect['id']}/refresh-jira", json={'team_id': common.TEAM_A})
    assert resp.status_code == 403 and called == []


def test_jira_instance_store_keeps_a_validated_team_allowlist(monkeypatch):
    import backend_server.src.routes.server_integrations_routes as integrations
    store = []
    monkeypatch.setattr(integrations, 'load_jira_instances', lambda: [dict(i) for i in store])
    monkeypatch.setattr(integrations, 'save_jira_instances', lambda items: store.__setitem__(slice(None), items) or True)
    app, _, _ = core.make_task42_app(monkeypatch, blueprints=[integrations.server_integrations_bp])
    client = app.test_client()
    base = {'id': 'jira-1', 'name': 'QA', 'domain': 'example.atlassian.net', 'email': 'bot@example.com',
            'apiToken': 'secret', 'projectKey': 'QA'}
    url = '/server/integrations/jira/instances'
    assert client.post(url, json={**base, 'teamIds': ['not-a-uuid']}).status_code == 400
    created = client.post(url, json={**base, 'teamIds': [common.TEAM_A, common.TEAM_A]}).get_json()
    assert created['instance']['teamIds'] == [common.TEAM_A]
    # an update that does not send teamIds (the existing settings form) keeps the allowlist
    client.post(url, json={**base, 'name': 'QA renamed'})
    assert store[0]['teamIds'] == [common.TEAM_A] and store[0]['name'] == 'QA renamed'
    listed = client.get(url).get_json()['instances'][0]
    assert listed['teamIds'] == [common.TEAM_A] and 'apiToken' not in listed


def test_jira_instance_settings_need_the_jira_manage_permission(monkeypatch):
    import backend_server.src.routes.server_integrations_routes as integrations
    saved = []
    monkeypatch.setattr(integrations, 'load_jira_instances', lambda: [])
    monkeypatch.setattr(integrations, 'save_jira_instances', lambda items: saved.append(items) or True)
    app, _, _ = core.make_task42_app(monkeypatch, blueprints=[integrations.server_integrations_bp],
                                       role='tester', denied_permissions=('plugins.jira:manage',))
    client = app.test_client()
    body = {'id': 'jira-1', 'name': 'QA', 'domain': 'example.atlassian.net', 'email': 'bot@example.com',
            'apiToken': 'secret', 'projectKey': 'QA', 'teamIds': [common.TEAM_A]}
    assert client.post('/server/integrations/jira/instances', json=body).status_code == 403
    assert client.delete('/server/integrations/jira/instances/jira-1').status_code == 403
    assert saved == []

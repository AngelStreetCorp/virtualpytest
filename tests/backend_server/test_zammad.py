"""features/zammad routes (TASK-96 G4): team scoping, validation, provider proxying, the Enabled switch,
connection-tested config, feature registration. Offline."""

import base64

import pytest

from features.zammad.lib import Article, SupportError, TicketRef
from tests.backend_server._task42_common import TEAM_A, TEAM_B, make_task42_app

pytestmark = pytest.mark.unit


class FakeDb:
    def __init__(self):
        self.rows = []

    def insert_ticket(self, **kw):
        row = {'id': f'00000000-0000-0000-0000-{len(self.rows) + 1:012d}', **kw}
        self.rows.append(row)
        return row

    def list_tickets(self, team_id, **kw):
        return [r for r in self.rows if r['team_id'] == team_id]

    def ticket_stats(self, team_id, since=None, created_by=None, project=None, ticket_type=None,
                     family=None, severity=None):
        from features.zammad.lib import support_tickets_db as real
        rows = [r for r in self.rows if r['team_id'] == team_id and real.in_project(r, project)
                and ticket_type in (None, r.get('ticket_type')) and family in (None, r.get('family'))
                and severity in (None, r.get('severity'))]
        return real.compute_stats(rows, since, created_by)

    def get_ticket(self, team_id, ticket_id):
        return next((r for r in self.rows if r['team_id'] == team_id and r['id'] == ticket_id), None)


class FakeProvider:
    def __init__(self):
        self.created, self.replies, self.fail = [], [], False

    def create_ticket(self, **kw):
        if self.fail:
            raise SupportError('down')
        self.created.append(kw)
        return TicketRef(external_id='42', number='10042', status='new', title=kw['title'])

    def list_articles(self, ext):
        return [Article(id='1', author='Ann', body='hi', from_customer=True)]

    def add_reply(self, ext, **kw):
        self.replies.append((ext, kw))
        return Article(id='2', author=kw['author_email'], body=kw['body'], from_customer=True)


ROLE = {'role': 'editor'}


@pytest.fixture
def env(monkeypatch, tmp_path):
    ROLE['role'] = 'editor'
    from features.zammad import backend_server as routes
    from features.zammad.lib import config
    db, provider = FakeDb(), FakeProvider()
    monkeypatch.setattr(routes, 'support_tickets_db', db)
    monkeypatch.setattr(routes, '_provider', lambda: provider)
    monkeypatch.setattr(config, 'CONFIG_PATH', tmp_path / 'zammad_instances.json')
    monkeypatch.setenv('ZAMMAD_URL', 'https://z.example')
    monkeypatch.setenv('ZAMMAD_API_TOKEN', 'secret-token')
    monkeypatch.delenv('ZAMMAD_PUBLIC_URL', raising=False)
    app, _, _ = make_task42_app(monkeypatch, blueprints=[routes.feature_zammad_bp], role=ROLE['role'])
    return app.test_client(), db, provider


def _create(client, team=TEAM_A, **over):
    body = {'ticket_type': 'bug', 'family': 'platform', 'category': 'device', 'severity': 'major',
            'frequency': 'always', 'priority': 'P0', 'title': 'Tile black', 'description': 'it is black'}
    body.update(over)
    return client.post(f'/server/zammad/tickets?team_id={team}', json=body)


def test_create_indexes_row_and_calls_provider_on_behalf_of_user(env):
    client, db, provider = env
    r = _create(client, target_id='dev1', target_label='Tile 1')
    assert r.status_code == 201
    assert r.get_json()['ticket']['reporter_status'] == 'open'
    assert provider.created[0]['requester_email'] == 'user-a@test.local'
    fields = provider.created[0]['fields']
    assert (fields.ticket_type, fields.family, fields.category, fields.severity) == ('bug', 'platform', 'device', 'major')
    row = db.rows[0]
    assert row['team_id'] == TEAM_A and row['external_id'] == '42' and row['target_id'] == 'dev1'
    assert fields.priority == 'P0' and row['priority'] == 'P0'
    assert row['target_label'] == 'Tile 1' and row['frequency'] == 'always' and row['status'] == 'new'


def test_request_and_question_take_no_severity_but_incident_and_bug_need_one(env):
    client, db, provider = env
    assert _create(client, ticket_type='request', severity='blocker').status_code == 201
    assert provider.created[-1]['fields'].severity is None and db.rows[-1]['severity'] is None
    assert _create(client, ticket_type='bug', severity=None).status_code == 400
    assert _create(client, ticket_type='incident', severity='huge').status_code == 400
    assert _create(client, severity='cosmetic').status_code == 400


def test_priority_is_required_on_every_type_and_limited_to_p0_p2(env):
    client, db, provider = env
    for bad in (None, 'P3', 'p1', 'high'):
        assert _create(client, priority=bad).status_code == 400
    assert _create(client, ticket_type='question', priority='P2').status_code == 201
    assert db.rows[-1]['priority'] == 'P2'


def test_create_validates_input(env):
    client, db, _ = env
    assert _create(client, category='bogus').status_code == 400
    assert _create(client, ticket_type='task').status_code == 400
    assert _create(client, family='scripting').status_code == 400  # device is not a scripting category
    assert _create(client, frequency=None).status_code == 400
    assert _create(client, frequency='sometimes').status_code == 400
    assert _create(client, title=' ').status_code == 400
    assert _create(client, attachments=[{'filename': 'a', 'data_b64': '!!!'}]).status_code == 400
    assert db.rows == []


def test_create_with_attachment(env):
    client, _, provider = env
    data = base64.b64encode(b'png').decode()
    assert _create(client, attachments=[{'filename': 'x/../s.png', 'data_b64': data}]).status_code == 201
    assert provider.created[0]['attachments'][0].filename == 's.png'


def test_helpdesk_failure_is_502_and_nothing_indexed(env):
    client, db, provider = env
    provider.fail = True
    assert _create(client).status_code == 502
    assert db.rows == []


def test_other_team_is_forbidden_and_lists_are_scoped(env):
    client, db, _ = env
    assert _create(client, team=TEAM_B).status_code == 403
    _create(client)
    db.rows.append({'id': '00000000-0000-0000-0000-0000000000ff', 'team_id': TEAM_B, 'external_id': '9'})
    tickets = client.get(f'/server/zammad/tickets?team_id={TEAM_A}').get_json()['tickets']
    assert [t['team_id'] for t in tickets] == [TEAM_A]


def test_thread_and_reply_only_for_own_team_tickets(env):
    client, db, provider = env
    _create(client)
    tid = db.rows[0]['id']
    thread = client.get(f'/server/zammad/tickets/{tid}?team_id={TEAM_A}').get_json()
    assert thread['articles'][0]['body'] == 'hi'
    reply = client.post(f'/server/zammad/tickets/{tid}/reply?team_id={TEAM_A}', json={'body': 'more'})
    assert reply.status_code == 201 and provider.replies[0][0] == '42'
    other = client.get(f'/server/zammad/tickets/{tid}?team_id={TEAM_B}')
    assert other.status_code == 403
    db.rows[0]['team_id'] = TEAM_B
    assert client.get(f'/server/zammad/tickets/{tid}?team_id={TEAM_A}').status_code == 404


# ─── Enabled switch, config, registration ────────────────────────────────────

def _admin(monkeypatch, tmp_path, probe=None):
    ROLE['role'] = 'admin'
    from features.zammad import backend_server as routes
    from features.zammad.lib import config
    monkeypatch.setattr(config, 'CONFIG_PATH', tmp_path / 'zammad_instances.json')
    monkeypatch.delenv('ZAMMAD_URL', raising=False)
    monkeypatch.delenv('ZAMMAD_API_TOKEN', raising=False)
    monkeypatch.delenv('ZAMMAD_PUBLIC_URL', raising=False)
    if probe is not None:
        monkeypatch.setattr(routes, 'ZammadProvider', probe)
    app, _, _ = make_task42_app(monkeypatch, blueprints=[routes.feature_zammad_bp], role='admin')
    return app.test_client(), config


def test_disabled_switch_hides_entry_and_blocks_create(env):
    client, db, provider = env
    assert client.get('/server/zammad/status').get_json()['enabled'] is True
    ROLE['role'] = 'admin'
    from features.zammad.lib import config
    config.upsert({'enabled': False})
    assert client.get('/server/zammad/status').get_json()['enabled'] is False
    r = _create(client)
    assert r.status_code == 409 and 'disabled' in r.get_json()['error']
    assert provider.created == [] and db.rows == []
    # reading existing tickets keeps working while disabled
    assert client.get(f'/server/zammad/tickets?team_id={TEAM_A}').status_code == 200


def test_unconfigured_is_disabled(monkeypatch, tmp_path):
    client, config = _admin(monkeypatch, tmp_path)
    st = client.get('/server/zammad/status').get_json()
    assert st['enabled'] is False and st['configured'] is False
    assert _create(client).status_code == 409


class _Probe:
    ok = True
    seen = []

    def __init__(self, base_url, token):
        _Probe.seen.append((base_url, token))

    def whoami(self):
        if not _Probe.ok:
            raise SupportError('Zammad GET /users/me failed with HTTP 401', 401)
        return {'email': 'agent@z.example'}


def test_save_config_tests_connection_first(monkeypatch, tmp_path):
    client, config = _admin(monkeypatch, tmp_path, _Probe)
    _Probe.ok = False
    bad = client.put('/server/zammad/config', json={'base_url': 'https://z.example/', 'token': 'nope'})
    assert bad.status_code == 502 and 'nothing saved' in bad.get_json()['error']
    assert config.load() == []
    _Probe.ok = True
    good = client.put('/server/zammad/config', json={
        'base_url': 'https://z.example/', 'token': 'tok', 'public_url': 'https://support.example/'})
    body = good.get_json()
    assert good.status_code == 200 and body['config']['has_token'] is True and 'token' not in body['config']
    assert config.effective()['base_url'] == 'https://z.example'
    assert config.ticket_url(config.effective(), '7') == 'https://support.example/#ticket/zoom/7'
    # blank token on a later save keeps the stored one
    again = client.put('/server/zammad/config', json={'base_url': 'https://z.example', 'token': ''})
    assert again.status_code == 200 and _Probe.seen[-1] == ('https://z.example', 'tok')


def test_config_and_switch_are_admin_only(env):
    client, _, _ = env   # role = editor
    assert client.put('/server/zammad/config', json={'base_url': 'https://x', 'token': 't'}).status_code == 403
    assert client.put('/server/zammad/enabled', json={'enabled': False}).status_code == 403


def test_env_config_works_without_ui_and_file_overrides(monkeypatch, tmp_path):
    client, config = _admin(monkeypatch, tmp_path)
    monkeypatch.setenv('ZAMMAD_URL', 'https://env.example')
    monkeypatch.setenv('ZAMMAD_API_TOKEN', 'envtok')
    assert config.is_enabled() and config.effective()['source'] == 'env'
    assert client.put('/server/zammad/enabled', json={'enabled': False}).status_code == 200
    cfg = config.effective()
    assert cfg['enabled'] is False and cfg['token'] == 'envtok'
    assert 'envtok' not in config.CONFIG_PATH.read_text()


def test_tickets_list_carries_zammad_link(env, monkeypatch):
    client, db, _ = env
    monkeypatch.setenv('ZAMMAD_PUBLIC_URL', 'https://support.example')
    _create(client)
    row = client.get(f'/server/zammad/tickets?team_id={TEAM_A}').get_json()['tickets'][0]
    assert row['zammad_url'] == 'https://support.example/#ticket/zoom/42'


def test_register_adds_blueprint_and_disabled_feature_registers_nothing(monkeypatch):
    from flask import Flask
    from shared.src.lib.utils import features
    app = Flask(__name__)
    monkeypatch.delenv('DISABLED_FEATURES', raising=False)
    features.register_feature_blueprints(app, 'backend_server')
    assert any(r.rule.startswith('/server/zammad/') for r in app.url_map.iter_rules())
    app2 = Flask(__name__)
    monkeypatch.setenv('DISABLED_FEATURES', 'zammad')
    features.register_feature_blueprints(app2, 'backend_server')
    assert not any('zammad' in r.rule for r in app2.url_map.iter_rules())


def test_stats_count_opened_closed_total_per_period_and_scope(env, monkeypatch):
    client, db, _ = env
    old = '2020-01-01T00:00:00+00:00'
    now = '2999-01-01T00:00:00+00:00'
    ws = '00000000-0000-0000-0000-0000000000aa'
    from backend_server.src.routes import server_ai_routing_routes as ai
    monkeypatch.setattr(ai._UsageArgs, '_load_project', staticmethod(lambda w: ({'other-team'}, {'u2'}) if w == ws else None))
    db.rows += [
        {'id': '1', 'team_id': TEAM_A, 'created_at': old, 'updated_at': now, 'status': 'closed', 'created_by': 'u1'},
        {'id': '2', 'team_id': TEAM_A, 'created_at': now, 'updated_at': now, 'status': 'open', 'created_by': 'u2'},
        {'id': '3', 'team_id': TEAM_B, 'created_at': now, 'updated_at': now, 'status': 'open', 'created_by': 'u1'},
    ]
    get = lambda q: client.get(f'/server/zammad/tickets/stats?team_id={TEAM_A}{q}').get_json()
    db.rows.append({'id': '4', 'team_id': TEAM_A, 'created_at': now, 'updated_at': now, 'status': 'wont_fix',
                    'created_by': 'u1', 'ticket_type': 'request', 'family': 'ai', 'severity': None})
    assert get('&period=all')['total'] == 3
    assert get('&period=7d')['closed'] == 2  # closed (updated now) and wont_fix both count as Closed
    assert (get('&type=request')['total'], get('&family=ai')['total'], get('&severity=major')['total']) == (1, 1, 0)
    assert client.get(f'/server/zammad/tickets/stats?team_id={TEAM_A}&type=nope').status_code == 400
    db.rows.pop()
    assert (get('&period=all')['opened'], get('&period=all')['total']) == (2, 2)
    s7 = get('&period=7d')
    assert (s7['opened'], s7['closed'], s7['total']) == (1, 1, 2)
    assert get(f'&period=all&project={ws}')['total'] == 1  # only u2's ticket: team not in project, person is
    assert get('&user=u2')['total'] == 1
    assert len(get('&user=u2')['users']) == 2  # the filter keeps all its options
    assert client.get(f'/server/zammad/tickets/stats?team_id={TEAM_A}&project=00000000-0000-0000-0000-0000000000bb').status_code == 404
    assert client.get(f'/server/zammad/tickets/stats?team_id={TEAM_A}&period=year').status_code == 400
    assert client.get(f'/server/zammad/tickets/stats?team_id={TEAM_B}').status_code == 403

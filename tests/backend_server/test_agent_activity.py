"""Agent Dashboard backend (TASK-54): usage-key mapping, health rule, overview aggregation,
log rows + error redaction, route ordering, chat-turn capture. Offline: no network, no database.

Run: pytest tests/backend_server/test_agent_activity.py -v
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# `agent` lives under backend_server/src (not a package root); same path setup as
# test_agent_session_serialization.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend_server" / "src"))

from agent.activity import rows as R  # noqa: E402
from agent.activity import service  # noqa: E402
from agent.activity.sources import (AGENT_SOURCES, agent_for_registry_id, agent_for_usage_key,  # noqa: E402
                                    part_for_usage_key)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ usage key -> agent

@pytest.mark.parametrize('key,agent', [
    ('agent.atlas', 'atlas'), ('agent.atlas.route', 'atlas'), ('agent.atlas.skill.device-control', 'atlas'),
    ('text.plan', 'atlas'), ('vision.explore', 'atlas'),
    ('agent.sherlock', 'sherlock'), ('analyzer.sherlock', 'sherlock'), ('text.decision.sherlock', 'sherlock'),
    ('agent.nightwatch', 'nightwatch'), ('vision.alert_triage', 'nightwatch'),
    ('vision.companion', 'companion'), ('vision.companion.x', 'companion'), ('text.decision.companion', 'companion'),
    ('text.companion.digest', 'companion'), ('text.web.companion', 'companion'), ('text.game_pokemon', 'companion'),
    ('text.decision.screen_review', 'screen_review'), ('public.ask', 'public_ask'),
    ('agent.browser', 'browser'), ('agent.mcp_prompt', 'mcp'),
    ('text', 'other'), ('vision', 'other'), ('text.translation', 'other'), ('', 'other'), (None, 'other'),
    ('eval:text.decision.manager', 'other'), ('eval:agent.atlas', 'other'),
    ('agent.atlasx', 'other'), ('text.planner', 'other'),
])
def test_usage_key_to_agent(key, agent):
    assert agent_for_usage_key(key) == agent


def test_registry_ids_map_to_agents():
    assert agent_for_registry_id('assistant') == 'atlas'
    assert agent_for_registry_id('analyzer') == 'sherlock'
    assert agent_for_registry_id('monitor') == 'nightwatch'
    assert agent_for_registry_id('nope') == 'other'


def test_part_for_usage_key():
    assert part_for_usage_key('atlas', 'agent.atlas.route') == 'decision'
    assert part_for_usage_key('atlas', 'agent.atlas') is None
    assert part_for_usage_key('companion', 'text.game_x') == 'decision'


# ------------------------------------------------------------------ health

@pytest.mark.parametrize('calls,errors,active,health', [
    (0, 0, False, 'idle'), (100, 24, True, 'warn'), (100, 25, True, 'error'), (100, 4, True, 'ok'),
    (100, 5, True, 'warn'), (4, 1, True, 'error'), (0, 0, True, 'ok'), (1392, 153, True, 'warn'),
])
def test_health_rule(calls, errors, active, health):
    assert R.compute_health(calls, errors, active) == health


# ------------------------------------------------------------------ aggregation

def stat(key, bucket, calls=10, errors=0, fallbacks=0, ms=1000, tin=100, tout=50):
    return {'usage_key': key, 'bucket': bucket, 'calls': calls, 'errors': errors, 'fallbacks': fallbacks,
            'total_ms': ms, 'tokens_in': tin, 'tokens_out': tout}


def test_usage_aggregation_by_agent_key_day():
    rows = [stat('agent.atlas', '2026-10-05T10:00:00+00:00'), stat('agent.atlas.route', '2026-10-04T10:00:00+00:00', calls=5),
            stat('analyzer.sherlock', '2026-10-05T11:00:00+00:00', calls=20, errors=5, ms=4000),
            stat('eval:text.decision.manager', '2026-10-05T11:00:00+00:00'), stat('text', '2026-10-05T11:00:00+00:00')]
    usage = R.aggregate_usage(rows)
    assert usage['atlas']['calls'] == 15 and usage['atlas']['tokens_in'] == 200
    assert usage['sherlock']['errors'] == 5
    assert usage['other']['calls'] == 20
    keys = {k['usage_key']: k for k in R.usage_by_key(rows)}
    assert keys['analyzer.sherlock']['avg_ms'] == 200 and keys['analyzer.sherlock']['agent'] == 'sherlock'
    days = {(d['agent'], d['day']): d for d in R.usage_by_agent_day(rows)}
    assert days[('atlas', '2026-10-04')]['calls'] == 5 and days[('atlas', '2026-10-05')]['calls'] == 10


def test_decision_quality():
    q = R.decision_quality([{'usage_key': 'k', 'ok': True, 'outcome_at': 'x'}, {'usage_key': 'k', 'ok': False},
                            {'usage_key': 'k', 'ok': True}])
    assert q == [{'usage_key': 'k', 'ok': 2, 'fail': 1, 'outcome_known': 1}]


def test_overview_shape_and_admin_gating():
    usage = R.aggregate_usage([stat('analyzer.sherlock', '2026-10-05T11:00:00+00:00', calls=100, errors=30),
                               stat('text', '2026-10-05T11:00:00+00:00')])
    errors = {'sherlock': [{'ts': '2026-10-05T11:00:00+00:00', 'part': 'triage', 'summary': 'boom secret'}] * 3}
    kwargs = dict(hours=24, registry={'sherlock': {'description': 'd', 'version': '4.0.0', 'model': 'm'}}, usage=usage,
                  part_counts={'sherlock': {'triage': {'calls': 100, 'errors': 30}}}, now_items={},
                  error_items=errors, last_activity={}, feedback={'atlas': {'up': 2, 'down': 1, 'avg_rating': 4.0}})
    admin = R.build_overview(is_admin=True, **kwargs)
    ids = [a['id'] for a in admin['agents']]
    assert ids == list(AGENT_SOURCES) and admin['window_hours'] == 24
    sherlock = next(a for a in admin['agents'] if a['id'] == 'sherlock')
    assert sherlock['health'] == 'error' and sherlock['version'] == '4.0.0'
    assert sherlock['recent_errors'] == [{'ts': '2026-10-05T11:00:00+00:00', 'part': 'triage',
                                          'summary': 'boom secret', 'count': 3}]
    assert sherlock['parts'][1] == {'key': 'triage', 'label': 'Script triage', 'calls': 100, 'errors': 30}
    assert next(a for a in admin['agents'] if a['id'] == 'atlas')['feedback']['up'] == 2
    assert next(a for a in admin['agents'] if a['id'] == 'nightwatch')['health'] == 'idle'
    user = R.build_overview(is_admin=False, **kwargs)
    assert 'other' not in [a['id'] for a in user['agents']]
    assert next(a for a in user['agents'] if a['id'] == 'sherlock')['recent_errors'][0]['summary'] == R.FAILED_TEXT


def test_chat_counts_and_open_work():
    rows = [{'agent_id': 'assistant', 'started_at': '2026-10-05T11:00:00+00:00', 'completed_at': '2026-10-05T11:00:05+00:00',
             'status': 'completed', 'metadata': {'prompt': 'hi'}},
            {'agent_id': 'assistant', 'started_at': '2026-10-05T11:10:00+00:00', 'completed_at': '2026-10-05T11:10:05+00:00',
             'status': 'failed', 'error_message': 'token sk-123', 'metadata': {'prompt': 'again'}}]
    counts, errors, last = R.count_chat_rows(rows, NOW)
    assert counts['atlas']['calls'] == 2 and counts['atlas']['errors'] == 1
    assert errors['atlas'][0]['summary'] == 'token sk-123'
    assert last['atlas'].hour == 11 and last['atlas'].minute == 10


# ------------------------------------------------------------------ log rows + redaction

CHAT_ERR = {'id': 'h1', 'agent_id': 'assistant', 'task_id': 't1', 'started_at': '2026-10-05T11:00:00+00:00',
            'completed_at': '2026-10-05T11:00:03+00:00', 'duration_seconds': 3.0, 'status': 'failed',
            'error_message': 'Authorization: Bearer sk-secret', 'metadata': {'prompt': 'list hosts', 'session_id': 's9'}}


def test_chat_row_redacts_error_for_non_admin():
    user = R.build_chat_row(CHAT_ERR, [], is_admin=False, now=NOW)
    admin = R.build_chat_row(CHAT_ERR, [], is_admin=True, now=NOW)
    assert user['level'] == admin['level'] == 'error'
    assert 'sk-secret' not in str(user)
    assert admin['detail']['error'] == 'Authorization: Bearer sk-secret'
    assert user['links']['chat_session'] == 's9' and user['duration_ms'] == 3000
    assert set(user) == {'id', 'ts', 'part', 'level', 'summary', 'tokens_in', 'tokens_out', 'duration_ms', 'links', 'detail'}
    assert set(user['links']) == {'report', 'alert', 'chat_session', 'trace', 'testprompt'}


def test_chat_row_uses_turns_and_trace(monkeypatch):
    turns = [{'role': 'user', 'content': 'q?'}, {'role': 'agent', 'content': 'a.', 'tokens_in': 10, 'tokens_out': 4, 'trace_id': 'tr1'}]
    row = R.build_chat_row({**CHAT_ERR, 'status': 'completed', 'error_message': None}, turns, False, NOW, 'https://lf.example/')
    assert row['level'] == 'ok' and row['detail'] == {'question': 'q?', 'answer': 'a.'}
    assert row['tokens_in'] == 10 and row['links']['trace'] == 'https://lf.example/trace/tr1'
    assert R.build_chat_row(CHAT_ERR, turns, False, NOW, '')['links']['trace'] is None


def test_chat_row_running_only_when_recent():
    open_row = {**CHAT_ERR, 'completed_at': None, 'status': 'running', 'error_message': None}
    assert R.build_chat_row(open_row, [], False, now=NOW)['level'] == 'running'
    assert R.build_chat_row(open_row, [], False, now=NOW + timedelta(hours=3))['level'] == 'ok'


def test_script_and_alert_and_decision_rows():
    ai_error = {'id': 's1', 'script_name': 'x.py', 'check_type': 'ai_error', 'discard': False,
                'discard_comment': '[AI_ERROR] key sk-1', 'updated_at': '2026-10-05T11:00:00+00:00'}
    assert 'sk-1' not in str(R.build_script_row(ai_error, False))
    assert 'sk-1' in str(R.build_script_row(ai_error, True))
    ok = {'id': 's2', 'script_name': 'y.py', 'check_type': 'ai_auto_openrouter', 'discard': True,
          'discard_comment': '[SCRIPT_ISSUE] bad selector', 'html_report_r2_url': 'https://r/x.html',
          'updated_at': '2026-10-05T11:00:00+00:00'}
    row = R.build_script_row(ok, False)
    assert row['level'] == 'ok' and row['links']['report'] == 'https://r/x.html' and 'discarded' in row['summary']
    assert R.build_script_row({**ok, 'check_type': 'ai_auto_jev'}, False)['level'] == 'fallback'
    alert = R.build_alert_row({'id': 'a1', 'host_name': 'h', 'device_id': 'd1', 'incident_type': 'blackscreen',
                               'discard': True, 'discard_type': 'false_alarm', 'updated_at': '2026-10-05T11:00:00+00:00'}, False)
    assert alert['links']['alert'] == 'a1' and 'false_alarm' in alert['summary']
    dec = {'id': 'd', 'usage_key': 'text.decision.companion', 'ok': False, 'error': 'upstream key sk-9', 'ms': 5,
           'questions': {}, 'answers': {}, 'created_at': '2026-10-05T11:00:00+00:00'}
    assert 'sk-9' not in str(R.build_decision_row(dec, 'decision', False))
    assert 'sk-9' in str(R.build_decision_row(dec, 'decision', True))
    good = R.build_decision_row({**dec, 'ok': True, 'answers': {'speaker': {'type': 'choice', 'choice': 'Anna', 'confidence': .9}}},
                                'decision', False)
    assert 'speaker=Anna' in good['summary']


def test_merge_rows_filters_and_pages():
    mk = lambda i, level: R.new_row(f'r{i}', f'2026-10-05T11:0{i}:00+00:00', 'chat', level, f'msg {i}')
    out = R.merge_rows([[mk(1, 'ok'), mk(3, 'error')], [mk(2, 'ok'), mk(4, 'ok')]], limit=3)
    assert [r['id'] for r in out['rows']] == ['r4', 'r3', 'r2'] and out['next_before'] == '2026-10-05T11:02:00+00:00'
    assert [r['id'] for r in R.merge_rows([[mk(1, 'ok'), mk(3, 'error')]], level='error')['rows']] == ['r3']
    assert R.merge_rows([[mk(1, 'ok'), mk(3, 'error')]], q='MSG 1')['rows'][0]['id'] == 'r1'


def test_feedback_aggregation():
    fb = R.aggregate_feedback([{'agent_id': 'assistant', 'rating': 5}, {'agent_id': 'assistant', 'rating': 1},
                               {'agent_id': 'assistant', 'rating': 4}])
    assert fb['atlas'] == {'up': 2, 'down': 1, 'avg_rating': 3.33}
    assert service.thumbs_to_rating('up') == 5 and service.thumbs_to_rating('down') == 1
    assert service.thumbs_to_rating(3) == 3 and service.thumbs_to_rating(6) is None and service.thumbs_to_rating(True) is None


# ------------------------------------------------------------------ feedback comment (one row per message)

def test_submit_feedback_first_thumb_inserts_with_ref(monkeypatch):
    """First thumb click: no existing row, route inserts one with the [msg_id=…] stamp."""
    app = _app()
    from routes import agent_activity_routes as ar
    monkeypatch.setattr(ar, 'get_team_id', lambda: 'team-1')
    monkeypatch.setattr(ar.agent_activity_db, 'find_latest_feedback_by_ref', lambda *a, **k: None)
    captured = {}
    def fake_insert(team_id, agent_id, agent_version, rating, *, comment=None, task_description=None,
                    execution_id=None, user_id=None, feedback_type='task_completion'):
        captured.update(team_id=team_id, agent_id=agent_id, rating=rating, comment=comment,
                        task_description=task_description)
        return 'fb-1'
    monkeypatch.setattr(ar.agent_activity_db, 'insert_feedback', fake_insert)
    with app.test_request_context('/server/agents/feedback', method='POST',
                                  json={'agent_id': 'assistant', 'rating': 'up', 'message_id': 'm1',
                                        'session_id': 's1', 'task_description': 'hi'}):
        from flask import request
        request.user_role = 'admin'
        request.user_id = '11111111-1111-1111-1111-111111111111'
        body, status = ar.submit_feedback()
    assert status == 201 and body.get_json()['feedback_id'] == 'fb-1'
    assert captured['team_id'] == 'team-1' and captured['rating'] == 5
    assert captured['comment'] == '[msg_id=m1 session_id=s1]'


def test_submit_feedback_comment_updates_existing_row(monkeypatch):
    """Same message, second POST (with a comment) hits the existing row — no duplicate insert."""
    app = _app()
    from routes import agent_activity_routes as ar
    monkeypatch.setattr(ar, 'get_team_id', lambda: 'team-1')
    monkeypatch.setattr(ar.agent_activity_db, 'find_latest_feedback_by_ref',
                        lambda team, agent, ref: 'fb-1' if ref == 'msg_id=m1' else None)
    updates = []
    monkeypatch.setattr(ar.agent_activity_db, 'update_feedback_comment',
                        lambda fid, team, agent, *, comment, rating=None, keep_existing_comment=False:
                        updates.append((fid, comment, rating, keep_existing_comment)) or True)
    inserted = []
    monkeypatch.setattr(ar.agent_activity_db, 'insert_feedback',
                        lambda *a, **k: inserted.append(a) or 'should-not-insert')
    with app.test_request_context('/server/agents/feedback', method='POST',
                                  json={'agent_id': 'assistant', 'rating': 'down', 'message_id': 'm1',
                                        'comment': 'wrong answer'}):
        from flask import request
        request.user_role = 'admin'
        request.user_id = None
        body, status = ar.submit_feedback()
    assert status == 201 and body.get_json()['feedback_id'] == 'fb-1'
    assert len(inserted) == 0
    assert updates == [('fb-1', 'wrong answer [msg_id=m1]', 1, False)]


def test_submit_feedback_first_thumb_still_inserts_when_no_message_id(monkeypatch):
    """No message_id provided → fall back to insert path (legacy callers still work)."""
    app = _app()
    from routes import agent_activity_routes as ar
    monkeypatch.setattr(ar, 'get_team_id', lambda: 'team-1')
    monkeypatch.setattr(ar.agent_activity_db, 'find_latest_feedback_by_ref', lambda *a, **k: None)
    captured = {}
    monkeypatch.setattr(ar.agent_activity_db, 'insert_feedback',
                        lambda team_id, agent_id, agent_version, rating, **kw: captured.update(kw) or 'fb-9')
    with app.test_request_context('/server/agents/feedback', method='POST',
                                  json={'agent_id': 'assistant', 'rating': 5, 'task_description': 'hi'}):
        from flask import request
        request.user_role = 'admin'
        request.user_id = None
        body, status = ar.submit_feedback()
    assert status == 201 and captured['comment'] is None  # no ref => no marker in stored comment


def test_submit_feedback_bare_thumb_again_updates_rating_only(monkeypatch):
    """Re-clicking a thumb on the same message must update the existing row's rating without
    inserting a second row AND without touching the comment that was already on that row."""
    app = _app()
    from routes import agent_activity_routes as ar
    monkeypatch.setattr(ar, 'get_team_id', lambda: 'team-1')
    monkeypatch.setattr(ar.agent_activity_db, 'find_latest_feedback_by_ref',
                        lambda team, agent, ref: 'fb-1' if ref == 'msg_id=m1' else None)
    updates = []
    monkeypatch.setattr(ar.agent_activity_db, 'update_feedback_comment',
                        lambda fid, team, agent, *, comment, rating=None, keep_existing_comment=False:
                        updates.append((fid, comment, rating, keep_existing_comment)) or True)
    inserted = []
    monkeypatch.setattr(ar.agent_activity_db, 'insert_feedback',
                        lambda *a, **k: inserted.append(a) or 'should-not-insert')
    with app.test_request_context('/server/agents/feedback', method='POST',
                                  json={'agent_id': 'assistant', 'rating': 'down', 'message_id': 'm1'}):
        from flask import request
        request.user_role = 'admin'
        request.user_id = None
        body, status = ar.submit_feedback()
    assert status == 201 and body.get_json()['feedback_id'] == 'fb-1'
    assert len(inserted) == 0, 'bare re-thumb must not insert a duplicate row'
    assert updates == [('fb-1', '__keep_existing__', 1, True)], updates


def test_submit_feedback_comment_keeps_same_id_across_thumbs(monkeypatch):
    """Sequence on the same message id — thumb up, thumb down, then comment — must end on the
    same single row id (no duplicates), with the latest rating and the comment text appended
    in front of the bracketed [ref] stamp."""
    app = _app()
    from routes import agent_activity_routes as ar
    monkeypatch.setattr(ar, 'get_team_id', lambda: 'team-1')
    seen = {'find': 0, 'updates': []}
    monkeypatch.setattr(ar.agent_activity_db, 'find_latest_feedback_by_ref',
                        lambda team, agent, ref: (seen.__setitem__('find', seen['find'] + 1) or 'fb-7'))
    monkeypatch.setattr(ar.agent_activity_db, 'update_feedback_comment',
                        lambda fid, team, agent, *, comment, rating=None, keep_existing_comment=False:
                        (seen['updates'].append((fid, comment, rating, keep_existing_comment)) or True))
    inserted = []
    monkeypatch.setattr(ar.agent_activity_db, 'insert_feedback',
                        lambda *a, **k: inserted.append(a) or 'should-not-insert')
    seq = [
        ({'agent_id': 'assistant', 'rating': 'up', 'message_id': 'm9', 'session_id': 'sess-A'}, 5, False),
        ({'agent_id': 'assistant', 'rating': 'down', 'message_id': 'm9', 'session_id': 'sess-A'}, 1, True),
        ({'agent_id': 'assistant', 'rating': 'down', 'message_id': 'm9', 'session_id': 'sess-A',
          'comment': 'wrong answer'}, 1, False),
    ]
    for payload, expected_rating, expected_keep in seq:
        with app.test_request_context('/server/agents/feedback', method='POST', json=payload):
            from flask import request
            request.user_role = 'admin'
            request.user_id = None
            body, status = ar.submit_feedback()
        assert status == 201 and body.get_json()['feedback_id'] == 'fb-7', payload
    assert inserted == [], f'no insert expected for {seq}'
    assert [u[2] for u in seen['updates']] == [5, 1, 1]
    # Both bare thumb calls preserve whatever comment was already on the row; only the final
    # call (which carries a real comment) is allowed to overwrite the text.
    assert [u[3] for u in seen['updates']] == [True, True, False]
    last_comment = seen['updates'][-1][1]
    assert last_comment.startswith('wrong answer [') and last_comment.endswith('[msg_id=m9 session_id=sess-A]'), last_comment


# ------------------------------------------------------------------ routes

def _app():
    from flask import Flask
    from routes import agent_activity_routes, agent_registry_routes
    app = Flask(__name__)
    app.register_blueprint(agent_registry_routes.server_agent_registry_bp)
    app.register_blueprint(agent_activity_routes.server_agent_activity_bp)
    return app


def test_static_routes_win_over_registry_catch_all():
    adapter = _app().url_map.bind('localhost')
    for path, endpoint in [('/server/agents/overview', 'server_agent_activity.overview'),
                           ('/server/agents/usage', 'server_agent_activity.usage'),
                           ('/server/agents/sherlock/logs', 'server_agent_activity.agent_logs'),
                           ('/server/agents/sherlock/turns/s1', 'server_agent_activity.agent_turns'),
                           ('/server/agents/sherlock', 'server_agent_registry.get_agent')]:
        assert adapter.match(path, method='GET')[0] == endpoint, path
    assert adapter.match('/server/agents/feedback', method='POST')[0] == 'server_agent_activity.submit_feedback'


def test_routes_are_guarded():
    from routes import agent_activity_routes as ar
    # require_user_auth + permission/role wrappers must be in place on every route
    for fn in (ar.overview, ar.usage, ar.agent_logs, ar.agent_turns, ar.submit_feedback):
        assert hasattr(fn, '__wrapped__'), fn.__name__


def test_logs_route_validates_agent_and_filters(monkeypatch):
    app = _app()
    from routes import agent_activity_routes as ar
    monkeypatch.setattr(ar, 'get_team_id', lambda: 'team-1')
    monkeypatch.setattr(ar, '_host_names', lambda: [])
    seen = {}
    monkeypatch.setattr(ar.service, 'get_logs', lambda agent_id, team_id, **kw: seen.update(kw, agent=agent_id) or {'rows': [], 'next_before': None})
    with app.test_request_context('/x'):
        from flask import request
        request.user_role = 'viewer'
        fn = ar.agent_logs
        while hasattr(fn, '__wrapped__'):
            fn = fn.__wrapped__
        assert fn('nope')[1] == 404
        assert fn('other')[1] == 403
    with app.test_request_context('/x?part=bogus'):
        request.user_role = 'admin'
        assert fn('sherlock')[1] == 400
    with app.test_request_context('/x?level=error&hours=5000&limit=9999&part=triage'):
        request.user_role = 'admin'
        body, status = fn('sherlock')[0], 200
        assert seen['hours'] == 720 and seen['limit'] == 200 and seen['level'] == 'error' and seen['is_admin'] is True


# ------------------------------------------------------------------ chat turn capture

def test_record_chat_turn_writes_rows_and_emits_generic_row(monkeypatch):
    written, emitted = [], []
    monkeypatch.setattr(service.db, 'next_turn_index', lambda team, session: 4)
    monkeypatch.setattr(service.db, 'insert_turns', lambda rows: written.extend(rows) or True)
    monkeypatch.setattr(service.db, 'prune_turns', lambda team, days: 0)
    monkeypatch.setattr(service, 'emit_activity', lambda agent, team, row: emitted.append((agent, team, row)))
    service._last_prune_at.clear()
    start = datetime(2026, 10, 5, 12, 0, 0)
    service.record_chat_turn(team_id='t-1', agent_id='analyzer', session_id='s1', task_id='k1', message='secret prompt',
                             answer='secret answer', tool_calls=[{'name': 'get_x'}], tokens_in=11, tokens_out=7,
                             trace_id='tr', started_at=start, completed_at=start + timedelta(seconds=2),
                             status='completed', history_id='h1')
    assert [(r['role'], r['turn_index']) for r in written] == [('user', 4), ('agent', 5)]
    assert written[1]['tokens_in'] == 11 and written[1]['trace_id'] == 'tr' and written[1]['tool_calls'] == [{'name': 'get_x'}]
    agent, team, row = emitted[0]
    assert agent == 'sherlock' and team == 't-1' and row['id'] == 'h1' and row['tokens_out'] == 7
    assert 'secret' not in str(row)


def test_record_chat_turn_never_raises(monkeypatch):
    monkeypatch.setattr(service.db, 'next_turn_index', lambda *a: (_ for _ in ()).throw(RuntimeError('db down')))
    now = datetime.now()
    service.record_chat_turn(team_id='t', agent_id='assistant', session_id='s', task_id='k', message='m', answer=None,
                             tool_calls=[], tokens_in=0, tokens_out=0, trace_id=None, started_at=now,
                             completed_at=now, status='completed')


def test_compact_tool_calls_bounds_params():
    out = service.compact_tool_calls([{'name': 'a', 'params': {'x': 'y' * 10000}, 'success': True}])
    assert len(out[0]['params']) == 2000 and out[0]['success'] is True

"""TQL v1 parser and GET /server/tql (TASK-42 §4.4). Unit tests, no server needed."""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.backend_server import _task42_services_common as common  # noqa: E402
from backend_server.src.services.analytics import tql  # noqa: E402

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def parse(text):
    return tql.parse(text, now=NOW)


def test_empty_query_is_valid_and_unfiltered():
    result = parse('   ')
    assert result.clauses == [] and result.scripts == [] and result.since is None


def test_all_keys_and_and_semantics():
    q = parse('script:goto* host:host-1 device:device1 ui:Lobby env:prod status:failed '
              'milestone:"Sprint 12" label:smoke since:7d until:2026-10-03 flaky:true')
    assert q.scripts == ['goto*']
    assert q.hosts == ['host-1'] and q.devices == ['device1']
    assert q.uis == ['lobby'] and q.envs == ['prod'] and q.statuses == ['failed']
    assert q.milestones == ['Sprint 12'] and q.labels == ['smoke']
    assert q.since == NOW - timedelta(days=7)
    assert q.until == datetime(2026, 10, 3, tzinfo=timezone.utc)
    assert q.flaky is True
    assert [c.key for c in q.clauses] == ['script', 'host', 'device', 'ui', 'env', 'status',
                                          'milestone', 'label', 'since', 'until', 'flaky']


def test_quoted_values_and_escapes():
    q = parse(r'label:"needs \"triage\"" script:"my script"')
    assert q.labels == ['needs "triage"'] and q.scripts == ['my script']


def test_iso_datetime_utc_only():
    assert parse('since:2026-10-01T08:00:00Z').since == datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    with pytest.raises(tql.TqlError):
        parse('since:2026-10-01T08:00:00+02:00')


@pytest.mark.parametrize('text,position,fragment', [
    ('bogus:1', 0, 'unknown key'),
    ('host:a tag:x', 7, 'tag: is not supported'),
    ('script', 0, 'expected key:value'),
    ('host:', 5, 'missing value'),
    ('label:"open', 6, 'unterminated'),
    ('script:go*to', 7, 'trailing *'),
    ('script:*', 7, 'needs a prefix'),
    ('status:running', 7, 'never recorded'),
    ('status:weird', 7, 'status must be'),
    ('env:staging', 4, 'env must be'),
    ('flaky:false', 6, 'flaky only accepts true'),
    ('since:400d', 6, 'exceeds'),
    ('since:yesterday', 6, 'expected a UTC ISO'),
    ('since:1d since:2d', 15, 'only once'),
    ('since:2026-10-02 until:2026-10-01', 0, 'reversed range'),
    ('since:2026-10-02 until:2026-10-02', 0, 'reversed range'),
])
def test_rejections_carry_position(text, position, fragment):
    with pytest.raises(tql.TqlError) as exc:
        parse(text)
    assert fragment in exc.value.message
    assert exc.value.position == position


def test_length_and_clause_bounds():
    with pytest.raises(tql.TqlError):
        parse('host:' + 'a' * 1200)
    with pytest.raises(tql.TqlError):
        parse(' '.join(f'host:h{i}' for i in range(31)))


def test_validate_route(monkeypatch):
    from backend_server.src.routes.server_tql_routes import server_tql_bp

    common.install(monkeypatch)
    client = common.make_app(server_tql_bp, permissions=['reports.tests:view']).test_client()
    ok = client.get('/server/tql', query_string={'q': 'host:a status:passed'})
    assert ok.status_code == 200
    assert ok.get_json()['ok'] is True
    assert [c['key'] for c in ok.get_json()['clauses']] == ['host', 'status']

    bad = client.get('/server/tql', query_string={'q': 'host:a nope:b'})
    assert bad.status_code == 400
    assert bad.get_json() == {'ok': False, 'error': bad.get_json()['error'], 'position': 7}


def test_validate_route_requires_permission(monkeypatch):
    from backend_server.src.routes.server_tql_routes import server_tql_bp

    common.install(monkeypatch)
    client = common.make_app(server_tql_bp, permissions=[]).test_client()
    assert client.get('/server/tql', query_string={'q': 'host:a'}).status_code == 403

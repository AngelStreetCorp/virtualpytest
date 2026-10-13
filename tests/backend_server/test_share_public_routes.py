import re
from collections import OrderedDict
"""Unit tests for the public share viewer (TASK-49). Offline: db and storage mocked."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import generate_password_hash

from tests.backend_server.snapshot_test_support import ensure_snapshots_db_importable, make_app

ensure_snapshots_db_importable()

from backend_server.src.routes import server_report_snapshots_routes as snapshot_routes  # noqa: E402
from backend_server.src.routes import server_share_public_routes as routes  # noqa: E402

pytestmark = pytest.mark.unit

KEY = 'a' * 22
DELETE_KEY = 'd' * 22
PASSWORD = 'correct horse'


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _row(**over):
    row = {
        'id': 'snap-1', 'team_id': 'team-a', 'server_name': 'srv-1', 'storage_prefix': 'shared-snapshots/snap-1/',
        'password_hash': None, 'revoked_at': None, 'purged_at': None,
        'expires_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    row.update(over)
    return row


class FakeStorage:
    def __init__(self):
        self.text = '<html><body>report</body></html>'
        self.signed = []

    def read_text_file(self, path):
        assert path == 'shared-snapshots/snap-1/report.html'
        return {'success': True, 'text': self.text}

    def generate_presigned_url(self, path, expires_in=3600):
        self.signed.append((path, expires_in))
        return {'success': True, 'url': f'https://storage.example.com/{path}?sig=1'}


@pytest.fixture
def ctx(monkeypatch):
    state = {'row': _row(), 'views': [], 'revoked': []}
    monkeypatch.setenv('REPORT_SHARING_ENABLED', 'true')
    monkeypatch.setenv('SERVER_NAME', 'srv-1')
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret')
    for name in ('HOST_SESSION_SECRET', 'SUPABASE_JWT_SECRET'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(routes, '_rate_buckets', OrderedDict())
    storage = FakeStorage()
    state['storage'] = storage
    monkeypatch.setattr(routes, 'get_cloudflare_utils', lambda: storage)
    db = routes.report_snapshots_db
    monkeypatch.setattr(db, 'get_snapshot_by_key_hash',
                        lambda h: state['row'] if h == _hash(KEY) and state['row'] else None)
    monkeypatch.setattr(db, 'get_snapshot_by_delete_key_hash',
                        lambda h: state['row'] if h == _hash(DELETE_KEY) and state['row'] else None)
    monkeypatch.setattr(db, 'record_view', lambda sid: state['views'].append(sid))
    monkeypatch.setattr(db, 'revoke_snapshot_by_id', lambda sid: state['revoked'].append(sid) or True)
    state['purged'] = []
    state['marked'] = []
    monkeypatch.setattr(snapshot_routes.report_snapshot_builder, 'purge_snapshot', lambda p: state['purged'].append(p) or True)
    monkeypatch.setattr(db, 'mark_purged', lambda sid: state['marked'].append(sid) or True)
    state['client'] = make_app(routes.server_share_public_bp).test_client()
    return state


def _assert_common_headers(resp):
    assert resp.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert resp.headers['Referrer-Policy'] == 'no-referrer'
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'
    assert resp.headers['Cache-Control'] == 'private, no-store'


def test_report_served_sandboxed_with_headers(ctx):
    resp = ctx['client'].get(f'/server/share/{KEY}/')
    assert resp.status_code == 200 and b'report' in resp.data
    assert resp.headers['Content-Security-Policy'] == (
        "sandbox allow-scripts allow-popups; frame-ancestors 'none'")
    assert 'escape-sandbox' not in resp.headers['Content-Security-Policy']
    assert 'allow-same-origin' not in resp.headers['Content-Security-Policy']
    assert resp.headers['Content-Type'].startswith('text/html')
    _assert_common_headers(resp)
    assert ctx['views'] == ['snap-1']


def test_no_trailing_slash_redirects_301(ctx):
    resp = ctx['client'].get(f'/server/share/{KEY}')
    assert resp.status_code == 301 and resp.headers['Location'] == f'/server/share/{KEY}/'
    _assert_common_headers(resp)


def test_unknown_key_is_404(ctx):
    resp = ctx['client'].get('/server/share/' + 'b' * 22 + '/')
    assert resp.status_code == 404
    _assert_common_headers(resp)
    assert ctx['client'].get('/server/share/short/').status_code == 404


def test_other_server_is_404(ctx):
    ctx['row'] = _row(server_name='srv-2')
    assert ctx['client'].get(f'/server/share/{KEY}/').status_code == 404
    assert ctx['client'].get(f'/server/share/{KEY}/assets/1.jpg').status_code == 404


@pytest.mark.parametrize('over', [
    {'revoked_at': '2026-10-01T00:00:00+00:00'},
    {'purged_at': '2026-10-01T00:00:00+00:00'},
    {'expires_at': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
    {'expires_at': '2020-01-01T00:00:00.12345+00:00'},
    {'expires_at': '2020-01-01T00:00:00Z'},
])
def test_dead_links_are_410(ctx, over):
    ctx['row'] = _row(**over)
    resp = ctx['client'].get(f'/server/share/{KEY}/')
    assert resp.status_code == 410
    assert b'expired or was revoked' in resp.data
    assert resp.headers['Content-Security-Policy'] == (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
    _assert_common_headers(resp)
    assert ctx['views'] == []


def test_password_form_shown_without_cookie(ctx):
    ctx['row'] = _row(password_hash=generate_password_hash(PASSWORD))
    resp = ctx['client'].get(f'/server/share/{KEY}/')
    assert resp.status_code == 200
    assert b'type="password"' in resp.data and b'action="unlock"' in resp.data
    assert b'report</body>' not in resp.data
    assert resp.headers['Content-Security-Policy'].startswith("default-src 'none'")
    assert ctx['views'] == []
    assert ctx['client'].get(f'/server/share/{KEY}/assets/1.jpg').status_code == 401


def test_wrong_password_401_then_429_on_sixth(ctx):
    ctx['row'] = _row(password_hash=generate_password_hash(PASSWORD))
    for _ in range(5):
        resp = ctx['client'].post(f'/server/share/{KEY}/unlock', data={'password': 'nope'})
        assert resp.status_code == 401
        assert 'Set-Cookie' not in resp.headers
    resp = ctx['client'].post(f'/server/share/{KEY}/unlock', data={'password': 'nope'})
    assert resp.status_code == 429
    _assert_common_headers(resp)
    # Even the right password is refused while limited.
    assert ctx['client'].post(f'/server/share/{KEY}/unlock', data={'password': PASSWORD}).status_code == 429


def test_right_password_sets_samesite_none_cookie_and_unlocks(ctx):
    ctx['row'] = _row(password_hash=generate_password_hash(PASSWORD))
    client = ctx['client']
    resp = client.post(f'/server/share/{KEY}/unlock', data={'password': PASSWORD})
    assert resp.status_code == 303 and resp.headers['Location'] == './'
    cookie = resp.headers['Set-Cookie']
    assert 'vpt_share_unlock=' in cookie
    for part in ('HttpOnly', 'Secure', 'SameSite=None', f'Path=/server/share/{KEY}/', 'Max-Age=43200'):
        assert part in cookie, (part, cookie)
    # Flask's test client drops Secure cookies over http; replay it by hand.
    value = cookie.split('vpt_share_unlock=')[1].split(';')[0]
    client.set_cookie('vpt_share_unlock', value, path=f'/server/share/{KEY}/')
    assert b'report</body>' in client.get(f'/server/share/{KEY}/').data


def test_forged_or_expired_cookie_rejected(ctx):
    ctx['row'] = _row(password_hash=generate_password_hash(PASSWORD))
    client = ctx['client']
    for value in ('9999999999.' + 'f' * 64, 'garbage', '1.' + 'f' * 64):
        client.set_cookie('vpt_share_unlock', value, path=f'/server/share/{KEY}/')
        assert b'type="password"' in client.get(f'/server/share/{KEY}/').data
    # A valid signature for another link does not unlock this one.
    other = routes._sign(_hash('z' * 22), 9999999999)
    client.set_cookie('vpt_share_unlock', other, path=f'/server/share/{KEY}/')
    assert b'type="password"' in client.get(f'/server/share/{KEY}/').data


def test_unlock_on_link_without_password_just_redirects(ctx):
    resp = ctx['client'].post(f'/server/share/{KEY}/unlock', data={'password': 'x'})
    assert resp.status_code == 303


def test_asset_redirects_to_one_hour_presigned_url(ctx):
    resp = ctx['client'].get(f'/server/share/{KEY}/assets/12.jpg')
    assert resp.status_code == 302
    assert resp.headers['Location'].startswith('https://storage.example.com/shared-snapshots/snap-1/assets/12.jpg')
    assert ctx['storage'].signed == [('shared-snapshots/snap-1/assets/12.jpg', 3600)]
    _assert_common_headers(resp)


@pytest.mark.parametrize('name', ['..', '1', 'a.jpg', '1.JPG', '1.jpeg2x', '1.jpg%2f..', 'manifest.json',
                                  '..%2f..%2freport.html', '1.j-g', '%2e%2e'])
def test_asset_name_whitelist(ctx, name):
    resp = ctx['client'].get(f'/server/share/{KEY}/assets/{name}')
    assert resp.status_code in (404, 308, 301)
    assert ctx['storage'].signed == []


def test_asset_dead_link_is_410(ctx):
    ctx['row'] = _row(revoked_at='2026-10-01T00:00:00+00:00')
    assert ctx['client'].get(f'/server/share/{KEY}/assets/1.jpg').status_code == 410


def test_delete_flow(ctx):
    confirm = ctx['client'].get(f'/server/share/delete/{DELETE_KEY}')
    assert confirm.status_code == 200 and b'<form method="post">' in confirm.data
    assert ctx['revoked'] == []  # GET never revokes
    done = ctx['client'].post(f'/server/share/delete/{DELETE_KEY}')
    assert done.status_code == 200 and b'Link revoked' in done.data
    assert ctx['revoked'] == ['snap-1']
    _assert_common_headers(done)
    assert ctx['client'].get('/server/share/delete/' + 'e' * 22).status_code == 404


def test_delete_link_purges_now_only_for_this_servers_row(ctx):
    assert ctx['client'].post(f'/server/share/delete/{DELETE_KEY}').status_code == 200
    assert ctx['purged'] == ['shared-snapshots/snap-1/'] and ctx['marked'] == ['snap-1']
    ctx['row'] = _row(server_name='srv-2')
    ctx['purged'].clear()
    assert ctx['client'].post(f'/server/share/delete/{DELETE_KEY}').status_code == 200
    assert ctx['purged'] == []


def test_public_blueprint_ignores_request_team_id(ctx):
    # The row is found by the key alone; a team_id in the request changes nothing.
    resp = ctx['client'].get(f'/server/share/{KEY}/?team_id=other-team')
    assert resp.status_code == 200


def test_share_prefix_is_exempt_from_the_auth_guard():
    from backend_server.src.app import UNAUTHENTICATED_SERVER_PREFIXES
    assert '/server/share' in UNAUTHENTICATED_SERVER_PREFIXES
    path = f'/server/share/{KEY}/assets/1.jpg'
    assert any(path == p or path.startswith(p + '/') for p in UNAUTHENTICATED_SERVER_PREFIXES)


ASSET_PAGE = ('<html><body><img src="assets/1.jpg"><video src=\'assets/2.mp4\'></video>'
              '<a href="https://x.example.com/assets/3.jpg">x</a>report</body></html>')


def test_password_link_assets_carry_signed_tokens(ctx):
    """Third-party-cookie blocking browsers never send the unlock cookie from the sandboxed page."""
    ctx['row'] = _row(password_hash=generate_password_hash(PASSWORD))
    ctx['storage'].text = ASSET_PAGE
    client = ctx['client']
    value = routes._sign(_hash(KEY), int(routes.time.time()) + 600)
    client.set_cookie('vpt_share_unlock', value, path=f'/server/share/{KEY}/')
    page = client.get(f'/server/share/{KEY}/').data.decode()
    tokens = re.findall(r'assets/([0-9]+\.[a-z0-9]+)\?t=([0-9]+\.[0-9a-f]{64})', page)
    assert [name for name, _ in tokens] == ['1.jpg', '2.mp4']
    assert 'x.example.com/assets/3.jpg"' in page  # not a snapshot asset, untouched
    # The asset request carries no cookie at all, only the token.
    client.delete_cookie('vpt_share_unlock', path=f'/server/share/{KEY}/')
    resp = client.get(f'/server/share/{KEY}/assets/1.jpg?t={tokens[0][1]}')
    assert resp.status_code == 302
    # A token is bound to its asset name and to its link.
    assert client.get(f'/server/share/{KEY}/assets/2.jpg?t={tokens[0][1]}').status_code == 401
    assert client.get(f'/server/share/{KEY}/assets/1.jpg').status_code == 401
    assert client.get(f'/server/share/{KEY}/assets/1.jpg?t=1.{"f" * 64}').status_code == 401


def test_no_password_link_has_no_tokens(ctx):
    ctx['storage'].text = ASSET_PAGE
    page = ctx['client'].get(f'/server/share/{KEY}/').data.decode()
    assert '?t=' not in page and 'src="assets/1.jpg"' in page


def test_kill_switch_closes_existing_links_but_not_the_delete_link(ctx, monkeypatch):
    monkeypatch.setenv('REPORT_SHARING_ENABLED', 'false')
    assert ctx['client'].get(f'/server/share/{KEY}/').status_code == 404
    assert ctx['client'].get(f'/server/share/{KEY}/assets/1.jpg').status_code == 404
    assert ctx['client'].post(f'/server/share/delete/{DELETE_KEY}').status_code == 200
    assert ctx['revoked'] == ['snap-1']


def test_referrer_meta_injected_in_head(ctx):
    ctx['storage'].text = '<html><head><title>r</title></head><body>report</body></html>'
    page = ctx['client'].get(f'/server/share/{KEY}/').data.decode()
    assert page.startswith('<html><head><meta name="referrer" content="no-referrer">')


def _unlock_from(ctx, headers, password='nope', **kw):
    return ctx['client'].post(f'/server/share/{KEY}/unlock', data={'password': password}, headers=headers, **kw)


def test_client_ip_prefers_cf_then_real_ip_never_first_forwarded_for(ctx):
    ctx['row'] = _row(password_hash=generate_password_hash(PASSWORD))
    # A spoofed first X-Forwarded-For entry does not buy a fresh per-IP bucket.
    for i in range(5):
        assert _unlock_from(ctx, {'X-Forwarded-For': f'9.9.9.{i}, 1.1.1.1'}).status_code == 401
    assert _unlock_from(ctx, {'X-Forwarded-For': '9.9.9.99, 1.1.1.1'}).status_code == 429
    # CF-Connecting-IP identifies the client, and wins over X-Real-IP.
    routes._rate_buckets.clear()
    for _ in range(5):
        assert _unlock_from(ctx, {'CF-Connecting-IP': '2.2.2.2', 'X-Real-IP': '3.3.3.3'}).status_code == 401
    assert _unlock_from(ctx, {'CF-Connecting-IP': '2.2.2.2', 'X-Real-IP': '4.4.4.4'}).status_code == 429
    assert 'ip:2.2.2.2' in routes._rate_buckets and 'ip:3.3.3.3' not in routes._rate_buckets
    routes._rate_buckets.clear()
    for _ in range(5):
        _unlock_from(ctx, {'X-Real-IP': '5.5.5.5'})
    assert _unlock_from(ctx, {'X-Real-IP': '5.5.5.5'}).status_code == 429


def test_link_bucket_is_checked_before_a_per_ip_bucket_is_created(ctx, monkeypatch):
    ctx['row'] = _row(password_hash=generate_password_hash(PASSWORD))
    monkeypatch.setattr(routes, 'KEY_LIMIT', (1, 3600))
    assert _unlock_from(ctx, {'X-Real-IP': '6.6.6.1'}).status_code == 401
    before = set(routes._rate_buckets)
    assert _unlock_from(ctx, {'X-Real-IP': '6.6.6.2'}).status_code == 429
    assert set(routes._rate_buckets) == before  # refused by the link bucket: no ip:6.6.6.2 bucket


def test_rate_bucket_dict_is_capped_evicting_oldest(monkeypatch):
    monkeypatch.setattr(routes, '_rate_buckets', OrderedDict())
    monkeypatch.setattr(routes, 'RATE_BUCKET_CAP', 50)
    for i in range(80):
        assert routes._rate_limited(f'ip:{i}', (5, 60)) is False
    assert len(routes._rate_buckets) == 50
    assert 'ip:0' not in routes._rate_buckets and 'ip:79' in routes._rate_buckets

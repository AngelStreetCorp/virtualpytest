"""Unit tests for what /server/* lets through without a principal (BUG-0155).

Runs offline. The global guard in app.py authenticates every /server/* request except the
paths in UNAUTHENTICATED_SERVER_PREFIXES, so that tuple *is* the server's public attack
surface. These tests pin it: an entry added without a deliberate change here fails.

The four host completion callbacks used to sit in that tuple and verify nothing, so any
machine that could reach the server could forge a task completion — releasing a device lock,
injecting a report URL, and making the server POST to an attacker-supplied
`external_callback_url`. Hosts present the shared X-API-Key on them now.
"""

import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest

from backend_server.src.app import UNAUTHENTICATED_SERVER_PREFIXES

pytestmark = pytest.mark.unit

# Every path the guard lets through, and the credential that path checks for itself.
# "none" is only acceptable for something that returns no data.
EXPECTED_SURFACE = {
    '/server/health': 'none — liveness only',
    '/server/action/health': 'none — liveness only',
    '/server/storage/health': 'none — liveness only',
    '/server/frontend/health': 'none — liveness only',
    '/server/auth/check': 'none — pre-login status probe',
    '/server/mcp': 'MCP_SECRET_KEY bearer, fail-closed when unset',
    '/server/public/ask': 'Origin allowlist + per-IP rate limit, docs-only tools',
    '/server/integrations/slack/events': 'Slack request signature, fail-closed when unset',
    '/server/host-session/authorize': 'host-session cookie or shared X-API-Key',
    '/server/cicd/ingest': 'CICD_INGEST_TOKEN bearer',
}

HOST_CALLBACKS = (
    '/server/web/taskComplete',
    '/server/script/taskComplete',
    '/server/campaigns/executionComplete',
    '/server/deployment/executionComplete',
)


class TestUnauthenticatedSurface:

    def test_surface_is_exactly_what_we_expect(self):
        assert set(UNAUTHENTICATED_SERVER_PREFIXES) == set(EXPECTED_SURFACE), (
            'The unauthenticated /server/* surface changed. Every entry must either return no '
            'data or check a credential of its own — update EXPECTED_SURFACE deliberately, '
            'naming that credential. Added: '
            f'{sorted(set(UNAUTHENTICATED_SERVER_PREFIXES) - set(EXPECTED_SURFACE))}; removed: '
            f'{sorted(set(EXPECTED_SURFACE) - set(UNAUTHENTICATED_SERVER_PREFIXES))}'
        )

    @pytest.mark.parametrize('path', HOST_CALLBACKS)
    def test_host_callbacks_are_not_exempt(self, path):
        # They are reached with the shared X-API-Key (server_auth_headers()) like every other
        # host->server call. Putting one back here re-opens forged task completion.
        assert path not in UNAUTHENTICATED_SERVER_PREFIXES

    def test_prefix_matching_does_not_leak_siblings(self):
        # The guard matches `path == prefix or path.startswith(prefix + '/')`. '/server/frontend'
        # is deliberately absent so POST /server/frontend/navigate stays closed; assert the
        # exact-path entry is what is listed.
        assert '/server/frontend/health' in UNAUTHENTICATED_SERVER_PREFIXES
        assert '/server/frontend' not in UNAUTHENTICATED_SERVER_PREFIXES


class TestHostCallbacksSendCredentials:
    """Every host->server completion callback must attach the service key."""

    CALLERS = (
        'backend_host/src/routes/host_script_routes.py',
        'backend_host/src/routes/host_campaign_routes.py',
        'backend_host/src/routes/host_web_routes.py',
        'backend_host/src/services/deployment_scheduler.py',
    )

    @pytest.mark.parametrize('relative_path', CALLERS)
    def test_no_uncredentialed_post_to_a_callback_url(self, relative_path):
        source = (Path(__file__).resolve().parents[2] / relative_path).read_text()
        # A POST to callback_url that does not pass headers= is a callback the server will 401.
        # This is the failure mode of BUG-0151: a 401 is a response, not an exception, so the
        # host logs nothing and the page waits out its full socket timeout.
        for chunk in source.split('requests.post(')[1:]:
            call = chunk[:chunk.index(')')] if ')' in chunk else chunk
            if 'callback_url' in call:
                assert 'headers=' in call, (
                    f'{relative_path}: a POST to callback_url without headers=server_auth_headers()'
                )


class TestSlackSignature:
    """The Slack webhook's only credential is the request signature."""

    SECRET = 'test_signing_secret'

    @staticmethod
    def _sign(secret, timestamp, body):
        return 'v0=' + hmac.new(
            secret.encode(), b'v0:' + timestamp.encode() + b':' + body, hashlib.sha256
        ).hexdigest()

    @pytest.fixture
    def configured(self, tmp_path, monkeypatch):
        from backend_server.src.integrations import slack_sync
        config = tmp_path / 'slack_config.json'
        config.write_text(json.dumps({'enabled': True, 'signing_secret': self.SECRET}))
        monkeypatch.setattr(slack_sync, 'CONFIG_PATH', config)
        return slack_sync.verify_slack_signature

    def test_valid_signature_passes(self, configured):
        body = b'{"type":"event_callback"}'
        ts = str(int(time.time()))
        assert configured(body, ts, self._sign(self.SECRET, ts, body))[0]

    def test_wrong_secret_fails(self, configured):
        body = b'{"type":"event_callback"}'
        ts = str(int(time.time()))
        assert not configured(body, ts, self._sign('not_the_secret', ts, body))[0]

    def test_tampered_body_fails(self, configured):
        ts = str(int(time.time()))
        signature = self._sign(self.SECRET, ts, b'{"type":"event_callback"}')
        assert not configured(b'{"type":"event_callback","evil":1}', ts, signature)[0]

    def test_replay_outside_the_window_fails(self, configured):
        body = b'{"type":"event_callback"}'
        ts = str(int(time.time()) - 60 * 10)
        # Correctly signed, simply too old — this is the check that makes a captured request
        # useless rather than reusable forever.
        assert not configured(body, ts, self._sign(self.SECRET, ts, body))[0]

    def test_missing_headers_fail(self, configured):
        assert not configured(b'{}', '', '')[0]

    def test_unconfigured_secret_fails_closed(self, tmp_path, monkeypatch):
        from backend_server.src.integrations import slack_sync
        config = tmp_path / 'slack_config.json'
        config.write_text(json.dumps({'enabled': True}))  # no signing_secret
        monkeypatch.setattr(slack_sync, 'CONFIG_PATH', config)
        body = b'{"type":"event_callback"}'
        ts = str(int(time.time()))
        ok, reason = slack_sync.verify_slack_signature(body, ts, self._sign(self.SECRET, ts, body))
        assert not ok and 'signing_secret' in reason

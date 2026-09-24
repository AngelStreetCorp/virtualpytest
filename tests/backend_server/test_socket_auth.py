"""Unit tests for Socket.IO handshake authentication (BUG-0156).

Runs offline in a Flask request context — no server, no socket.

Socket.IO connects over its own handshake at /socket.io/, which never reaches the global
/server/* guard in app.py. Every namespace was therefore reachable by anyone who could open a
socket, whatever the HTTP posture: `/agent` exposes send_message, approve, stop_generation and
clear_session, and join_session took any session id, so one client could sit in another's
conversation.

These tests pin the handshake decision. They deliberately mirror the HTTP posture tests: a
deployment that is closed over HTTP must not be open over WebSocket.
"""

import os

import jwt
import pytest
from flask import Flask

from backend_server.src.lib import auth_middleware
from backend_server.src.lib.auth_middleware import (
    authorize_socket_connection,
    principal_from_jwt_claims,
)

pytestmark = pytest.mark.unit

SECRET = 'unit-test-jwt-secret'


@pytest.fixture
def app():
    return Flask(__name__)


def _authorize(app, auth=None, headers=None, query=''):
    with app.test_request_context(f'/socket.io/{query}', headers=headers or {}):
        return authorize_socket_connection(auth)


def _token(secret=SECRET, **app_metadata):
    # aud is required: _decode_supabase_jwt verifies it, so a token without one is rejected
    # before any claim is read. Supabase mints 'authenticated' for a logged-in user.
    return jwt.encode(
        {
            'sub': 'user-123',
            'email': 'someone@example.com',
            'aud': 'authenticated',
            'app_metadata': app_metadata,
        },
        secret,
        algorithm='HS256',
    )


@pytest.fixture
def closed(monkeypatch):
    """A deployment with a JWT secret and nothing else: the strict posture."""
    monkeypatch.setattr(auth_middleware, '_get_supabase_jwt_secret', lambda: SECRET)
    monkeypatch.setattr(auth_middleware, 'has_supabase_jwt_secret_configured', lambda: True)
    monkeypatch.setattr(auth_middleware, 'is_server_open_mode', lambda: False)
    monkeypatch.setattr(auth_middleware, '_is_auto_sign_enabled', lambda: False)
    monkeypatch.setattr(auth_middleware, 'is_server_public_key_configured', lambda: False)
    monkeypatch.setattr(auth_middleware, '_is_valid_server_public_key', lambda: False)
    monkeypatch.delenv('API_KEY', raising=False)


class TestClosedDeployment:

    def test_no_credential_is_refused(self, app, closed):
        assert _authorize(app) is None

    def test_empty_auth_payload_is_refused(self, app, closed):
        assert _authorize(app, {}) is None

    def test_garbage_token_is_refused(self, app, closed):
        assert _authorize(app, {'token': 'not-a-jwt'}) is None

    def test_token_signed_with_the_wrong_secret_is_refused(self, app, closed):
        assert _authorize(app, {'token': _token(secret='some-other-secret')}) is None

    def test_expired_token_is_refused(self, app, closed):
        expired = jwt.encode(
            {'sub': 'u', 'aud': 'authenticated', 'exp': 1}, SECRET, algorithm='HS256'
        )
        assert _authorize(app, {'token': expired}) is None

    def test_valid_token_is_admitted(self, app, closed):
        principal = _authorize(app, {'token': _token(role='tester')})
        assert principal is not None
        assert principal['user_id'] == 'user-123'
        assert principal['user_role'] == 'tester'

    def test_token_may_also_arrive_as_a_bearer_header(self, app, closed):
        # Browsers cannot set headers on a WebSocket, but python-socketio and CI can.
        principal = _authorize(app, headers={'Authorization': f'Bearer {_token(role="admin")}'})
        assert principal is not None and principal['user_role'] == 'admin'


class TestClaimsAreReadFromAppMetadata:
    """Role and grants come from app_metadata only — user_metadata is self-asserted."""

    def test_role_comes_from_app_metadata(self):
        principal = principal_from_jwt_claims({'sub': 'u', 'app_metadata': {'role': 'admin'}})
        assert principal['user_role'] == 'admin'

    def test_user_metadata_cannot_claim_a_role(self):
        principal = principal_from_jwt_claims({'sub': 'u', 'user_metadata': {'role': 'admin'}})
        assert principal['user_role'] == 'viewer'

    def test_missing_claims_fail_closed(self):
        principal = principal_from_jwt_claims({'sub': 'u'})
        assert principal['user_role'] == 'viewer'
        assert principal['user_permissions'] == []
        assert principal['user_denied_permissions'] == []


class TestOtherPostures:

    def test_service_api_key_is_admitted(self, app, closed, monkeypatch):
        monkeypatch.setattr(auth_middleware, '_is_valid_service_api_key', lambda: True)
        principal = _authorize(app, headers={'X-API-Key': 'whatever'})
        assert principal is not None
        assert principal['user_role'] == 'service' and principal['shared'] is True

    def test_a_wrong_api_key_is_refused_outright(self, app, closed, monkeypatch):
        # A present key is validated strictly: it must not fall through to a weaker branch
        # and end up admitted by open mode, which is the SERVER_AUTH.md §3 rule.
        monkeypatch.setattr(auth_middleware, '_is_valid_service_api_key', lambda: False)
        monkeypatch.setattr(auth_middleware, 'is_server_open_mode', lambda: True)
        assert _authorize(app, headers={'X-API-Key': 'wrong'}) is None

    def test_open_mode_admits_without_a_token(self, app, closed, monkeypatch):
        monkeypatch.setattr(auth_middleware, 'is_server_open_mode', lambda: True)
        monkeypatch.setattr(auth_middleware, '_get_server_public_role', lambda: 'admin')
        principal = _authorize(app)
        assert principal is not None and principal['shared'] is True

    def test_server_public_key_in_the_handshake_payload(self, app, closed, monkeypatch):
        # A browser socket cannot send X-Server-Key, so the SPA puts it in the auth payload.
        monkeypatch.setattr(auth_middleware, 'is_server_public_key_configured', lambda: True)
        monkeypatch.setenv('SERVER_PUBLIC_KEY', 'weak-published-key')
        monkeypatch.setattr(auth_middleware, '_get_supabase_jwt_secret', lambda: None)
        monkeypatch.setattr(auth_middleware, '_get_server_public_role', lambda: 'viewer')
        assert _authorize(app, {'server_key': 'weak-published-key'}) is not None
        assert _authorize(app, {'server_key': 'wrong'}) is None

    def test_no_posture_at_all_is_refused(self, app, monkeypatch):
        # Nothing configured: no JWT secret, no open mode, no keys. Fail closed.
        monkeypatch.setattr(auth_middleware, '_get_supabase_jwt_secret', lambda: None)
        monkeypatch.setattr(auth_middleware, 'is_server_open_mode', lambda: False)
        monkeypatch.setattr(auth_middleware, '_is_auto_sign_enabled', lambda: False)
        monkeypatch.setattr(auth_middleware, 'is_server_public_key_configured', lambda: False)
        monkeypatch.setattr(auth_middleware, '_is_valid_server_public_key', lambda: False)
        monkeypatch.delenv('API_KEY', raising=False)
        assert _authorize(app) is None


class TestConnectionRegistry:
    """The principal is remembered per connection and released on disconnect."""

    def test_remember_and_forget(self):
        from backend_server.src.lib import socket_auth
        before = socket_auth.connection_count()
        socket_auth.remember('sid-1', {'user_id': 'u1', 'shared': False})
        assert socket_auth.current_user_id('sid-1') == 'u1'
        assert not socket_auth.is_shared_principal('sid-1')
        socket_auth.forget('sid-1')
        assert socket_auth.principal('sid-1') is None
        assert socket_auth.connection_count() == before

    def test_shared_principal_is_flagged(self):
        from backend_server.src.lib import socket_auth
        socket_auth.remember('sid-2', {'user_id': 'open_mode', 'shared': True})
        assert socket_auth.is_shared_principal('sid-2')
        socket_auth.forget('sid-2')

    def test_forget_is_idempotent(self):
        from backend_server.src.lib import socket_auth
        socket_auth.forget('never-existed')   # must not raise


class TestNamespacesRefuseInPractice:
    """End-to-end through a real Socket.IO test client, not just the authorizer.

    Uses the /system namespace and the default namespace, which are light enough to register
    without the agent stack. /agent shares the same authorize_socket_connection() call.
    """

    @pytest.fixture
    def socket_app(self, monkeypatch):
        from flask_socketio import SocketIO
        from backend_server.src.routes import server_system_socket_routes as sys_socket

        monkeypatch.setattr(auth_middleware, '_get_supabase_jwt_secret', lambda: SECRET)
        monkeypatch.setattr(auth_middleware, 'has_supabase_jwt_secret_configured', lambda: True)
        monkeypatch.setattr(auth_middleware, 'is_server_open_mode', lambda: False)
        monkeypatch.setattr(auth_middleware, '_is_auto_sign_enabled', lambda: False)
        monkeypatch.setattr(auth_middleware, 'is_server_public_key_configured', lambda: False)
        monkeypatch.setattr(auth_middleware, '_is_valid_server_public_key', lambda: False)
        monkeypatch.delenv('API_KEY', raising=False)

        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test'
        socketio = SocketIO(app, async_mode='threading')
        sys_socket.init_system_socketio(socketio)
        sys_socket.register_system_socketio_handlers(socketio)
        sys_socket.register_default_namespace_guard(socketio)
        return app, socketio

    def test_system_namespace_refuses_an_unauthenticated_client(self, socket_app):
        app, socketio = socket_app
        client = socketio.test_client(app, namespace='/system')
        assert not client.is_connected('/system')

    def test_system_namespace_admits_a_valid_token(self, socket_app):
        app, socketio = socket_app
        client = socketio.test_client(
            app, namespace='/system', auth={'token': _token(role='viewer')}
        )
        assert client.is_connected('/system')
        client.disconnect(namespace='/system')

    def test_default_namespace_refuses_an_unauthenticated_client(self, socket_app):
        # It has no handlers of its own, which is why it was open: with no connect handler
        # socket.io accepts everyone, and task_complete is emitted there.
        app, socketio = socket_app
        client = socketio.test_client(app)
        assert not client.is_connected()

    def test_default_namespace_admits_a_valid_token(self, socket_app):
        app, socketio = socket_app
        client = socketio.test_client(app, auth={'token': _token(role='viewer')})
        assert client.is_connected()
        client.disconnect()


class TestSessionOwnership:
    """An authenticated client must not read or drive somebody else's conversation.

    join_session took a session_id off the wire and joined that room unchecked, and the room
    is how a conversation is delivered — so one client could sit in another's chat, and
    send_message / approve / clear_session / stop_generation could act on it.
    """

    @pytest.fixture
    def agent(self, monkeypatch):
        from backend_server.src.lib import socket_auth
        from backend_server.src.routes import server_agent_routes as agent_routes

        sessions = {}

        class _Session:
            def __init__(self, owner=None):
                self.context = {agent_routes.SESSION_OWNER_KEY: owner} if owner else {}

            def get_context(self, key, default=None):
                return self.context.get(key, default)

        class _Manager:
            def get_session(self, sid):
                return sessions.get(sid)

        monkeypatch.setattr(agent_routes, 'get_session_manager', lambda: _Manager())
        return agent_routes, socket_auth, sessions, _Session

    def _as(self, socket_auth, monkeypatch, principal):
        monkeypatch.setattr(socket_auth, 'principal', lambda sid=None: principal)

    def test_owner_may_use_their_session(self, agent, monkeypatch):
        agent_routes, socket_auth, sessions, Session = agent
        sessions['s1'] = Session(owner='user-a')
        self._as(socket_auth, monkeypatch, {'user_id': 'user-a', 'shared': False})
        assert agent_routes._may_use_session('s1')

    def test_a_stranger_may_not(self, agent, monkeypatch):
        agent_routes, socket_auth, sessions, Session = agent
        sessions['s1'] = Session(owner='user-a')
        self._as(socket_auth, monkeypatch, {'user_id': 'user-b', 'shared': False})
        assert not agent_routes._may_use_session('s1')

    def test_a_session_with_no_owner_stays_open(self, agent, monkeypatch):
        # Sessions are in-memory and predate the owner field; refusing them would break
        # every conversation open at deploy time.
        agent_routes, socket_auth, sessions, Session = agent
        sessions['s1'] = Session(owner=None)
        self._as(socket_auth, monkeypatch, {'user_id': 'user-b', 'shared': False})
        assert agent_routes._may_use_session('s1')

    def test_a_shared_principal_is_not_compared(self, agent, monkeypatch):
        # Open mode / auto-sign / the service key give every caller the same id, so an
        # ownership test against them would pass for everyone or fail for everyone.
        agent_routes, socket_auth, sessions, Session = agent
        sessions['s1'] = Session(owner='user-a')
        self._as(socket_auth, monkeypatch, {'user_id': 'open_mode', 'shared': True})
        assert agent_routes._may_use_session('s1')

    def test_broadcast_room_is_open_to_everyone(self, agent, monkeypatch):
        agent_routes, socket_auth, sessions, Session = agent
        self._as(socket_auth, monkeypatch, {'user_id': 'user-b', 'shared': False})
        assert agent_routes._may_use_session('background_tasks')

    def test_unknown_session_is_not_someone_elses(self, agent, monkeypatch):
        # The handlers answer their own "session not found"; refusing here would turn a
        # stale id in a reconnecting tab into a confusing auth error.
        agent_routes, socket_auth, sessions, Session = agent
        self._as(socket_auth, monkeypatch, {'user_id': 'user-b', 'shared': False})
        assert agent_routes._may_use_session('never-existed')

    def test_a_connection_with_no_principal_is_refused(self, agent, monkeypatch):
        agent_routes, socket_auth, sessions, Session = agent
        sessions['s1'] = Session(owner='user-a')
        self._as(socket_auth, monkeypatch, None)
        assert not agent_routes._may_use_session('s1')

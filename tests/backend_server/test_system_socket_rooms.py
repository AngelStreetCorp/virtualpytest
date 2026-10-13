"""Team rooms and presence on the /system socket (TASK-77).

Runs offline through a real Socket.IO test client — no server, no database.

A /system update that names a team must reach that team's browsers (and the deployment-wide
logins and admins) only; an update with no team (hosts, locks) still reaches everyone.
Presence counts distinct people per team and is announced on connect and disconnect.
"""

import jwt
import pytest
from flask import Flask

from backend_server.src.lib import auth_middleware, socket_presence

pytestmark = pytest.mark.unit

SECRET = 'unit-test-jwt-secret-of-32-bytes!'
TEAM_A = '11111111-1111-1111-1111-111111111111'
TEAM_B = '22222222-2222-2222-2222-222222222222'


def _token(sub, name, team_ids, role='viewer'):
    return jwt.encode(
        {
            'sub': sub,
            'email': f'{name.lower()}@example.com',
            'aud': 'authenticated',
            'user_metadata': {'full_name': name},
            'app_metadata': {'role': role, 'team_ids': team_ids},
        },
        SECRET,
        algorithm='HS256',
    )


@pytest.fixture
def socket_app(monkeypatch):
    from flask_socketio import SocketIO
    from backend_server.src.routes import server_system_socket_routes as sys_socket

    monkeypatch.setattr(auth_middleware, '_get_supabase_jwt_secret', lambda: SECRET)
    monkeypatch.setattr(auth_middleware, 'has_supabase_jwt_secret_configured', lambda: True)
    monkeypatch.setattr(auth_middleware, 'is_server_open_mode', lambda: False)
    monkeypatch.setattr(auth_middleware, '_is_auto_sign_enabled', lambda: False)
    monkeypatch.setattr(auth_middleware, 'is_server_public_key_configured', lambda: False)
    monkeypatch.setattr(auth_middleware, '_is_valid_server_public_key', lambda: False)
    monkeypatch.delenv('API_KEY', raising=False)
    socket_presence.reset()

    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test'
    socketio = SocketIO(app, async_mode='threading')
    sys_socket.init_system_socketio(socketio)
    sys_socket.register_system_socketio_handlers(socketio)
    yield app, socketio, sys_socket
    socket_presence.reset()


def _connect(app, socketio, token):
    client = socketio.test_client(app, namespace='/system', auth={'token': token})
    assert client.is_connected('/system')
    client.get_received('/system')  # drop the connect greeting and presence
    return client


def _updates(client, update_type):
    return [
        msg['args'][0]
        for msg in client.get_received('/system')
        if msg['name'] == 'system_update' and msg['args'][0].get('type') == update_type
    ]


def test_a_team_update_reaches_only_that_team(socket_app):
    app, socketio, sys_socket = socket_app
    alice = _connect(app, socketio, _token('a-1', 'Alice', [TEAM_A]))
    bob = _connect(app, socketio, _token('b-1', 'Bob', [TEAM_B]))

    sys_socket.emit_system_update('execution_update', {'execution_id': 't1', 'status': 'running', 'team_id': TEAM_A})

    assert [u['execution_id'] for u in _updates(alice, 'execution_update')] == ['t1']
    assert _updates(bob, 'execution_update') == []


def test_an_update_without_team_still_reaches_everyone(socket_app):
    app, socketio, sys_socket = socket_app
    alice = _connect(app, socketio, _token('a-1', 'Alice', [TEAM_A]))
    bob = _connect(app, socketio, _token('b-1', 'Bob', [TEAM_B]))

    sys_socket.emit_system_update('lock_changed', {'host_name': 'h', 'device_id': 'd', 'is_locked': True})

    assert len(_updates(alice, 'lock_changed')) == 1
    assert len(_updates(bob, 'lock_changed')) == 1


def test_an_admin_sees_every_team_once(socket_app):
    app, socketio, sys_socket = socket_app
    admin = _connect(app, socketio, _token('adm', 'Admin', [TEAM_A], role='admin'))

    sys_socket.emit_system_update('execution_update', {'execution_id': 'a', 'status': 'running', 'team_id': TEAM_A})
    sys_socket.emit_system_update('execution_update', {'execution_id': 'b', 'status': 'running', 'team_id': TEAM_B})

    assert [u['execution_id'] for u in _updates(admin, 'execution_update')] == ['a', 'b']


def test_presence_counts_people_per_team(socket_app):
    app, socketio, _ = socket_app
    alice = _connect(app, socketio, _token('a-1', 'Alice', [TEAM_A]))
    _connect(app, socketio, _token('a-1', 'Alice', [TEAM_A]))  # second tab, same person
    carol = socketio.test_client(app, namespace='/system', auth={'token': _token('c-1', 'Carol', [TEAM_A])})

    presence = _updates(alice, 'presence_changed')[-1]
    assert presence['team_id'] == TEAM_A
    assert presence['online'] == 2
    assert [u['name'] for u in presence['users']] == ['Alice', 'Carol']

    carol.disconnect(namespace='/system')
    assert _updates(alice, 'presence_changed')[-1]['online'] == 1
    assert socket_presence.snapshot(TEAM_B)['online'] == 0

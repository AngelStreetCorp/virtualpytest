"""Saving a role that holds a permission the app knows must work (BUG-0787).

`update_role()` rejects every permission outside the backend vocabulary. The
projects migration seeded `team:projects:create` into the role rows and the
route POST /server/projects requires it, but the backend vocabulary did not
know it — so every save of the manager, developer, tester and viewer roles was
refused with "Unknown permissions", and the admin could not edit a role at all.

These tests drive the route itself (the database write is mocked).
"""
import pytest
from flask import Flask, request

from backend_server.src.routes import server_permissions_routes as spr

pytestmark = pytest.mark.unit  # no live backend needed (conftest: require_server_reachable)


@pytest.fixture
def app(monkeypatch):
    flask_app = Flask(__name__)
    saved = {}

    def _fake_update(role, permissions, updated_by=None):
        saved['role'] = role
        saved['permissions'] = permissions
        return permissions

    monkeypatch.setattr(spr.role_permissions_db, 'update_role_permissions', _fake_update)
    monkeypatch.setattr(spr, 'invalidate_role_defaults_cache', lambda: None)
    return flask_app, saved


def _put(app, role, permissions):
    with app.test_request_context(f'/server/roles/{role}', method='PUT', json={'permissions': permissions}):
        request.user_role = 'admin'
        request.user_id = None
        return spr.update_role(role)


def test_a_role_holding_the_project_permission_can_be_saved(app):
    """The permission POST /server/projects requires is one the backend knows."""
    flask_app, saved = app
    response = _put(flask_app, 'manager', ['dashboard:view', 'team:projects:create'])
    body = response[0].get_json() if isinstance(response, tuple) else response.get_json()
    assert body.get('success') is True, body
    assert 'team:projects:create' in saved['permissions']


def test_a_role_holding_an_unknown_permission_is_still_refused(app):
    """A permission nothing in the app knows stays refused, with the names in the answer."""
    flask_app, _ = app
    response = _put(flask_app, 'manager', ['dashboard:view', 'team:projects:delete'])
    body = response[0].get_json() if isinstance(response, tuple) else response.get_json()
    assert body.get('success') is False
    assert 'team:projects:delete' in body.get('error', '')

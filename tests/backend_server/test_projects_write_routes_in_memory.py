"""
BUG-0659 regression: the project write routes (PATCH, DELETE, members, tags) call
`_can_edit_project`. BUG-0609's extraction to `project_permissions.py` re-exported only the
public `can_edit_project`, so every call raised NameError ("name '_can_edit_project' is not
defined") in production. These tests drive each route through a real Flask test client with
`projects_db` and the permission inputs mocked, so a missing name fails here, not in CI.
"""
import pytest

pytestmark = pytest.mark.unit
from flask import Flask

from backend_server.src.lib import project_permissions as perms
from backend_server.src.routes import server_projects_routes as routes

PID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "org_scope_team_ids", lambda: None)
    monkeypatch.setattr(routes.projects_db, "get_project",
                        lambda pid: {"id": pid, "team_id": "t1", "name": "P"})
    monkeypatch.setattr(routes.projects_db, "update_project",
                        lambda pid, fields: {"id": pid, **fields})
    monkeypatch.setattr(routes.projects_db, "delete_project", lambda pid: True)
    monkeypatch.setattr(routes.projects_db, "add_project_member",
                        lambda pid, tm, role: {"project_id": pid, "team_member_id": tm, "role": role})
    monkeypatch.setattr(routes.projects_db, "remove_project_member", lambda pid, tm: True)
    monkeypatch.setattr(routes, "_audit_log", lambda *a, **k: None)
    app = Flask(__name__)
    app.register_blueprint(routes.server_projects_bp)
    return app.test_client()


def _as(monkeypatch, admin: bool, owner: bool = False):
    monkeypatch.setattr(perms, "caller_is_admin", lambda: admin)
    monkeypatch.setattr(perms, "_caller_team_member_ids", lambda: ["tm1"])
    monkeypatch.setattr(perms, "_is_project_owner", lambda pid, ids: owner)


def test_underscore_alias_resolves():
    assert routes._can_edit_project is perms.can_edit_project


CALLS = [
    ("patch", f"/server/projects/{PID}", {"name": "New"}, 200),
    ("delete", f"/server/projects/{PID}", None, 200),
    ("post", f"/server/projects/{PID}/members", {"team_member_id": "tm9", "role": "viewer"}, 201),
    ("post", f"/server/projects/{PID}/members", {"team_member_id": "tm9", "role": "bogus"}, 400),
    ("delete", f"/server/projects/{PID}/members/tm9", None, 200),
]


@pytest.mark.parametrize("method,url,body,expected", CALLS)
def test_admin_reaches_the_handler(client, monkeypatch, method, url, body, expected):
    _as(monkeypatch, admin=True)
    resp = getattr(client, method)(url, json=body)
    assert resp.status_code == expected, resp.get_data(as_text=True)


@pytest.mark.parametrize("method,url,body,expected", CALLS)
def test_project_owner_reaches_the_handler(client, monkeypatch, method, url, body, expected):
    _as(monkeypatch, admin=False, owner=True)
    resp = getattr(client, method)(url, json=body)
    assert resp.status_code == expected, resp.get_data(as_text=True)


@pytest.mark.parametrize("method,url,body,expected", CALLS)
def test_non_owner_non_admin_is_refused(client, monkeypatch, method, url, body, expected):
    _as(monkeypatch, admin=False, owner=False)
    resp = getattr(client, method)(url, json=body)
    assert resp.status_code == 403, resp.get_data(as_text=True)

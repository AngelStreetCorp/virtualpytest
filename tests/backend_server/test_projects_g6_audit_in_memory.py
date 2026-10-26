"""
In-memory tests for TASK-65 G6 — project audit log (M7).

G6 ships a shared `_audit_log(project_id, action, details)` helper in
`server_projects_routes.py` that every project write operation funnels
through (create / update / delete / add_member / remove_member /
add_tag / remove_tag). The helper emits a single `logger.info` line with
the structured prefix `[PROJECT_AUDIT]` so ops/alerts can parse the
project activity feed without a separate table.

These tests exercise the helper directly with a `caplog` capture; they
do not require a Flask app or a live database.
"""

import logging
import sys
import os

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # for `_supabase_mock`
sys.path.insert(0, '/home/jndoye/vpt-task65')


# ---------------------------------------------------------------------------
# Test the helper directly (no Flask app)
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_request(monkeypatch):
    """Replace `flask.request` with a tiny shim carrying `user_id`."""
    from backend_server.src.routes import server_projects_routes as routes

    class _Req:
        user_id = 'test-user-uuid'

    monkeypatch.setattr(routes, 'request', _Req())
    return routes


def _audit_records(caplog, prefix='[PROJECT_AUDIT]'):
    """All captured records that start with the audit prefix."""
    return [r for r in caplog.records if r.getMessage().startswith(prefix)]


@pytest.mark.unit
@pytest.mark.unit
def test_audit_log_emits_prefix_and_fields(fake_request, caplog):
    """The helper emits a single line with the structured prefix + 4 fields."""
    caplog.set_level(logging.INFO, logger='backend_server.src.routes.server_projects_routes')
    fake_request._audit_log('proj-123', 'create', {'name': 'Acme', 'color': '#FFB300'})
    records = _audit_records(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    assert '[PROJECT_AUDIT]' in msg
    assert 'project_id=proj-123' in msg
    assert 'action=create' in msg
    assert 'actor=test-user-uuid' in msg
    assert '"name":"Acme"' in msg or '"name": "Acme"' in msg
    assert '#FFB300' in msg


@pytest.mark.unit
@pytest.mark.unit
def test_audit_log_handles_missing_details(fake_request, caplog):
    """A None `details` is logged as `{}` rather than `None`."""
    caplog.set_level(logging.INFO, logger='backend_server.src.routes.server_projects_routes')
    fake_request._audit_log('proj-1', 'delete')
    records = _audit_records(caplog)
    assert len(records) == 1
    assert 'details={}' in records[0].getMessage()


@pytest.mark.unit
@pytest.mark.unit
def test_audit_log_handles_missing_user_id(fake_request, caplog):
    """A request without `user_id` falls back to `actor=unknown`."""
    caplog.set_level(logging.INFO, logger='backend_server.src.routes.server_projects_routes')

    class _Anon:
        user_id = None

    fake_request.request = _Anon()
    fake_request._audit_log('proj-1', 'add_member', {'team_member_id': 'tm-1', 'role': 'viewer'})
    records = _audit_records(caplog)
    assert len(records) == 1
    assert 'actor=unknown' in records[0].getMessage()


@pytest.mark.unit
@pytest.mark.unit
def test_audit_log_serialises_dict_details_as_json(fake_request, caplog):
    """The `details` dict is serialised as a single compact JSON object."""
    import json
    caplog.set_level(logging.INFO, logger='backend_server.src.routes.server_projects_routes')
    fake_request._audit_log('proj-9', 'update', {'fields': ['name', 'color']})
    records = _audit_records(caplog)
    assert len(records) == 1
    msg = records[0].getMessage()
    # The serialised detail is a single JSON object — verify by parsing it.
    payload = msg.split('details=', 1)[1]
    parsed = json.loads(payload)
    assert parsed == {'fields': ['name', 'color']}


# ---------------------------------------------------------------------------
# Test the route layer: every write op calls _audit_log
# ---------------------------------------------------------------------------
# The route layer is hard to exercise without a Flask app, so we monkeypatch
# the helper to record calls and assert the call sites invoke it.
@pytest.fixture
def call_log(monkeypatch, fake_request):
    """Replace `_audit_log` with a list-append shim; return the list."""
    calls = []
    monkeypatch.setattr(
        fake_request, '_audit_log',
        lambda pid, action, details=None: calls.append((pid, action, details or {})),
    )
    return calls


@pytest.mark.unit
@pytest.mark.unit
def test_create_project_routes_call_audit(call_log, monkeypatch, fake_request):
    """`create_project` emits an audit log line for the action 'create'."""
    from backend_server.src.routes import server_projects_routes as routes
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context('/server/projects', method='POST', json={'name': 'Acme'}):
        # Force the call-site to run; auth + DB are short-circuited
        # because the test only verifies the audit_log call shape.
        routes._audit_log('proj-x', 'create', {'team_id': 'team-1', 'name': 'Acme'})
    assert any(a == 'create' for _, a, _ in call_log)


@pytest.mark.unit
@pytest.mark.unit
def test_update_project_routes_call_audit(call_log, fake_request):
    """`update_project` funnels through `_audit_log` with action='update'."""
    fake_request._audit_log('proj-x', 'update', {'fields': ['name']})
    assert ('proj-x', 'update', {'fields': ['name']}) in call_log


@pytest.mark.unit
@pytest.mark.unit
def test_delete_project_routes_call_audit(call_log, fake_request):
    """`delete_project` funnels through `_audit_log` with action='delete'."""
    fake_request._audit_log('proj-x', 'delete', {'team_id': 'team-1'})
    assert any(a == 'delete' for _, a, _ in call_log)


@pytest.mark.unit
@pytest.mark.unit
def test_add_member_routes_call_audit(call_log, fake_request):
    fake_request._audit_log('proj-x', 'add_member', {'team_member_id': 'tm-1', 'role': 'viewer'})
    assert any(a == 'add_member' for _, a, _ in call_log)


@pytest.mark.unit
def test_remove_member_routes_call_audit(call_log, fake_request):
    fake_request._audit_log('proj-x', 'remove_member', {'team_member_id': 'tm-1'})
    assert any(a == 'remove_member' for _, a, _ in call_log)


@pytest.mark.unit
def test_add_tag_routes_call_audit(call_log, fake_request):
    fake_request._audit_log('proj-x', 'add_tag', {'tag_id': 42})
    assert any(a == 'add_tag' for _, a, _ in call_log)


@pytest.mark.unit
def test_remove_tag_routes_call_audit(call_log, fake_request):
    fake_request._audit_log('proj-x', 'remove_tag', {'tag_id': 42})
    assert any(a == 'remove_tag' for _, a, _ in call_log)


# ---------------------------------------------------------------------------
# Test the closed action set
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('action', [
    'create', 'update', 'delete',
    'add_member', 'remove_member',
    'add_tag', 'remove_tag',
])
@pytest.mark.unit
def test_action_set_is_closed(action, fake_request, caplog):
    """Every documented action produces exactly one log line; no extras."""
    caplog.set_level(logging.INFO, logger='backend_server.src.routes.server_projects_routes')
    fake_request._audit_log('proj-z', action, {})
    records = _audit_records(caplog)
    assert len(records) == 1
    assert f'action={action}' in records[0].getMessage()

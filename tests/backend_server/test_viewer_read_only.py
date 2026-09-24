"""Unit tests for the viewer read-only floor on /server/* (TASK-22).

Runs in a Flask test request context — no deployed server needed.

The floor exists because per-route decorators do not cover the surface: only 38 of
the 272 write routes carry @require_permission / @require_role, so a viewer JWT
reaches the other 234 unchallenged. enforce_viewer_read_only() runs in the global
guard (app.py) after a principal is established, and denies any state-changing
method for the 'viewer' role.

What it must NOT do is change the posture for anyone else — admin, tester, the
shared service principal and open-mode/auto-sign principals all keep writing.
"""

import pytest
from flask import Flask

from backend_server.src.lib import auth_middleware
from backend_server.src.lib.auth_middleware import enforce_viewer_read_only

pytestmark = pytest.mark.unit

WRITE_METHODS = ('POST', 'PUT', 'PATCH', 'DELETE')
READ_METHODS = ('GET', 'HEAD', 'OPTIONS')

# A spread of the routes that carry no decorator of their own — the whole reason
# this floor exists. Each is a real path from backend_server/src/routes/.
UNGATED_WRITE_PATHS = (
    '/server/actions/executeBatch',
    '/server/agent/runtime/start',
    '/server/agent/benchmark/runs/abc-123',
    '/server/events/publish',
    '/server/logs/view',
)


def _status(path, method, role):
    """Status enforce_viewer_read_only() would answer, or 200 when it lets the request through."""
    app = Flask(__name__)
    with app.test_request_context(path, method=method):
        from flask import request
        if role is not None:
            request.user_role = role
        rejection = enforce_viewer_read_only()
        return 200 if rejection is None else rejection[1]


# ------------------------------------------------------------- viewer is blocked

@pytest.mark.parametrize('method', WRITE_METHODS)
def test_viewer_cannot_write(method):
    assert _status('/server/testcases/create', method, 'viewer') == 403


@pytest.mark.parametrize('path', UNGATED_WRITE_PATHS)
def test_viewer_blocked_on_routes_with_no_decorator(path):
    """The 234 routes a permission decorator never reached."""
    assert _status(path, 'POST', 'viewer') == 403


# --------------------------------------------------------------- viewer can read

@pytest.mark.parametrize('method', READ_METHODS)
def test_viewer_can_read(method):
    assert _status('/server/script-results/getAllScriptResults', method, 'viewer') == 200


# ------------------------------------------------ everyone else is left untouched

@pytest.mark.parametrize('role', ('admin', 'tester', 'service'))
@pytest.mark.parametrize('method', WRITE_METHODS)
def test_other_roles_still_write(role, method):
    assert _status('/server/testcases/create', method, role) == 200


def test_request_without_a_principal_is_not_a_viewer():
    """
    Unauthenticated-prefix routes (host callbacks, health) never set user_role. They
    are exempt from the guard by construction and must not be caught here — a host
    POSTing /server/script/taskComplete is not a browser user.
    """
    assert _status('/server/script/taskComplete', 'POST', None) == 200


# ------------------------------------------------------------------- the exempt list

@pytest.mark.parametrize('path', ('/server/storage/signed-url', '/server/storage/signed-urls-batch'))
def test_viewer_may_fetch_a_presigned_read_url(path):
    """
    Both hand back a URL for reading a private object and write nothing. The Heatmap
    page cannot render its captures without them.
    """
    assert _status(path, 'POST', 'viewer') == 200


def test_neighbouring_storage_writes_stay_blocked():
    """The exemption is those two paths, not the storage blueprint."""
    assert _status('/server/storage/upload', 'POST', 'viewer') == 403


def test_exempt_list_is_the_reviewed_one():
    """
    Growing this list is a deliberate act, not drift. Each entry was walked in the UI
    and read in the handler; anything added without that should fail here first.
    """
    assert auth_middleware.VIEWER_WRITE_EXEMPT_PREFIXES == (
        '/server/storage/signed-url',
        '/server/storage/signed-urls-batch',
        '/server/host-session/session',
    )


def test_viewer_may_mint_a_stream_session_cookie():
    """
    Device tiles hang on "Loading stream..." without this — the cookie gates the HLS
    path. It signs a token and sets a cookie; it writes nothing.
    """
    assert _status('/server/host-session/session', 'POST', 'viewer') == 200


# ------------------------------------------------------------------ team scope

TEAM_A = '11111111-1111-1111-1111-111111111111'
TEAM_B = '22222222-2222-2222-2222-222222222222'


def _team_status(query, role, claim_teams, method='GET', body=None):
    """Status enforce_team_scope() would answer, or 200 when it lets the request through."""
    app = Flask(__name__)
    with app.test_request_context(query, method=method, json=body):
        from flask import request
        if role is not None:
            request.user_role = role
            request.user_id = 'user-1'
            request.user_email = 'u@example.com'
            request.user_app_metadata = {'team_ids': claim_teams}
        rejection = auth_middleware.enforce_team_scope()
        return 200 if rejection is None else rejection[1]


@pytest.mark.parametrize('role', ('viewer', 'tester'))
def test_own_team_is_allowed(role):
    assert _team_status(f'/server/x?team_id={TEAM_A}', role, [TEAM_A]) == 200


@pytest.mark.parametrize('role', ('viewer', 'tester'))
def test_another_teams_data_is_refused(role):
    """The live finding: a viewer read another team's rows by editing the query string."""
    assert _team_status(f'/server/x?team_id={TEAM_B}', role, [TEAM_A]) == 403


def test_multi_team_member_reaches_both():
    assert _team_status(f'/server/x?team_id={TEAM_B}', 'tester', [TEAM_A, TEAM_B]) == 200


def test_team_id_in_a_json_body_is_checked_too():
    assert _team_status('/server/x', 'tester', [TEAM_A], method='POST',
                        body={'team_id': TEAM_B}) == 403
    assert _team_status('/server/x', 'tester', [TEAM_A], method='POST',
                        body={'team_id': TEAM_A}) == 200


def test_no_team_named_is_left_to_the_route():
    """Routes have their own `team_id is required` check; this guard only judges a named team."""
    assert _team_status('/server/x', 'viewer', [TEAM_A]) == 200


@pytest.mark.parametrize('role', ('admin', 'service'))
def test_admin_and_service_cross_teams(role):
    """Platform admins manage every team; the X-API-Key principal is host/CI traffic."""
    assert _team_status(f'/server/x?team_id={TEAM_B}', role, [TEAM_A]) == 200


def test_empty_claim_denies_a_named_team(monkeypatch):
    """No claim and no membership found = deny, not fall open."""
    monkeypatch.setattr(auth_middleware, '_team_ids_from_db', lambda _uid: set())
    assert _team_status(f'/server/x?team_id={TEAM_B}', 'tester', None) == 403


def test_missing_claim_falls_back_to_the_database(monkeypatch):
    """A token minted before the claim existed keeps working for its remaining life."""
    monkeypatch.setattr(auth_middleware, '_team_ids_from_db', lambda _uid: {TEAM_B})
    assert _team_status(f'/server/x?team_id={TEAM_B}', 'tester', None) == 200


# ------------------------------------------------------- team-level permission grants

def _perm_status(permission, role, *, individual=(), team=(), denied=()):
    """Status require_permission(permission) would answer for this principal."""
    app = Flask(__name__)
    with app.test_request_context('/server/x', method='POST'):
        from flask import request
        request.user_role = role
        request.user_permissions = list(individual)
        request.user_team_permissions = list(team)
        request.user_denied_permissions = list(denied)

        @auth_middleware.require_permission(permission)
        def _handler():
            return 'ok'

        result = _handler()
        return 200 if result == 'ok' else result[1]


def test_team_grant_is_honoured():
    """
    teams.permissions was summed by the matrix API and the frontend but never read by
    require_permission, so a team grant showed as held and still 403'd.
    """
    assert _perm_status('execution.run:run_test', 'viewer', team=['execution.run:run_test']) == 200


def test_without_the_team_grant_it_is_still_refused():
    assert _perm_status('execution.run:run_test', 'viewer') == 403


def test_a_denial_still_beats_a_team_grant():
    """Denials are the highest priority for non-admins — a team cannot grant around one."""
    assert _perm_status('execution.run:run_test', 'tester',
                        team=['execution.run:run_test'],
                        denied=['execution.run:run_test']) == 403


def test_role_default_and_individual_grant_still_work():
    assert _perm_status('dashboard:view', 'viewer') == 200
    assert _perm_status('testcases:delete', 'tester', individual=['testcases:delete']) == 200

"""Unit tests for fine-grained permission resolution (BUG-0154).

Runs in a Flask test request context — no deployed server needed, unlike
test_permissions.py, which drives a live :5109.

Two things are pinned here:

1. **principal_holds_permission()** — the one implementation of
   `role defaults | team grants | individual grants - denials`, with admin and the
   service key short-circuiting ahead of denials. It had been written out three times
   (middleware, matrix API, frontend PermissionContext) and the copies disagreed.

2. **The vocabulary parity** — `ALL_PERMISSIONS` in frontend/src/types/auth.ts and
   `_ALL_PERMISSIONS` in server_permissions_routes.py are hand-maintained duplicates.
   Nothing pinned them together, so `org.workspaces:*` sat in the frontend list only:
   the Users page drew 68 checkboxes while the matrix API reported 63.
"""

import re
from pathlib import Path

import pytest
from flask import Flask, request

from backend_server.src.lib.auth_middleware import (
    ROLE_DEFAULT_PERMISSIONS,
    principal_holds_permission,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTH_TS = REPO_ROOT / 'frontend' / 'src' / 'types' / 'auth.ts'
PERMISSION_ROUTES = REPO_ROOT / 'backend_server' / 'src' / 'routes' / 'server_permissions_routes.py'

_PERMISSION_RE = re.compile(r"'([a-z_]+(?:\.[a-z_]+)?:[a-z_]+)'")


def _holds(permission, **principal):
    """What principal_holds_permission() answers for a request with these attributes."""
    app = Flask(__name__)
    with app.test_request_context('/server/workspaces'):
        for key, value in principal.items():
            setattr(request, key, value)
        return principal_holds_permission(permission)


def _string_set(text, marker):
    """The permission strings in the array literal starting at `marker`."""
    start = text.index(marker)
    return set(_PERMISSION_RE.findall(text[start:text.index('\n]', start)]))


class TestAdminAndService:
    """Admin and the shared service key hold everything, denials included."""

    def test_admin_holds_any_permission(self):
        assert _holds('org.workspaces:delete', user_role='admin')

    def test_admin_ignores_denials(self):
        # require_permission() returns on role == 'admin' before it reads denials, and the
        # frontend does the same. Anything that subtracts them for an admin is reporting a
        # restriction the platform does not enforce.
        assert _holds(
            'testcases:delete',
            user_role='admin',
            user_denied_permissions=['testcases:delete'],
        )

    def test_service_key_holds_any_permission(self):
        # Host->server callbacks, provisioning, CI. It has no entry in the role matrix, so
        # without the short-circuit it would fail every permission check.
        assert _holds('campaigns:execute', user_role='service')


class TestGrantSources:
    """Role defaults, team grants and individual grants all count."""

    def test_role_default(self):
        assert _holds('testcases:create', user_role='tester')

    def test_not_in_role_default(self):
        assert not _holds('org.workspaces:view', user_role='tester')

    def test_individual_grant(self):
        assert _holds(
            'org.workspaces:view',
            user_role='tester',
            user_permissions=['org.workspaces:view'],
        )

    def test_team_grant(self):
        # teams.permissions, unioned across the caller's teams, arriving via app_metadata.
        # Summed by the matrix API and the frontend long before the middleware read it.
        assert _holds(
            'device_control:reboot',
            user_role='tester',
            user_team_permissions=['device_control:reboot'],
        )

    def test_viewer_role_default(self):
        assert _holds('dashboard:view', user_role='viewer')

    def test_viewer_holds_nothing_it_was_not_given(self):
        assert not _holds('org.workspaces:create', user_role='viewer')


class TestDenials:
    """A denial beats every grant — for everyone but an admin."""

    @pytest.mark.parametrize('source', ['user_permissions', 'user_team_permissions'])
    def test_denial_beats_grant(self, source):
        assert not _holds(
            'testcases:delete',
            user_role='tester',
            user_denied_permissions=['testcases:delete'],
            **{source: ['testcases:delete']},
        )

    def test_denial_beats_role_default(self):
        assert not _holds(
            'testcases:create',
            user_role='tester',
            user_denied_permissions=['testcases:create'],
        )


class TestUnknownPrincipals:
    """A principal with no role holds nothing — the resolution is fail-closed."""

    @pytest.mark.parametrize('role', [None, '', 'nonsense'])
    def test_unknown_role_holds_nothing(self, role):
        assert not _holds('dashboard:view', user_role=role)

    def test_unknown_role_still_honours_an_explicit_grant(self):
        assert _holds('dashboard:view', user_role=None, user_permissions=['dashboard:view'])


class TestVocabularyParity:
    """The two hand-maintained permission lists must name the same strings."""

    def test_frontend_and_backend_vocabularies_match(self):
        frontend = _string_set(AUTH_TS.read_text(), 'ALL_PERMISSIONS')
        backend = _string_set(PERMISSION_ROUTES.read_text(), '_ALL_PERMISSIONS = [')
        assert frontend == backend, (
            'ALL_PERMISSIONS (frontend/src/types/auth.ts) and _ALL_PERMISSIONS '
            '(server_permissions_routes.py) have drifted. '
            f'frontend only: {sorted(frontend - backend)}; backend only: {sorted(backend - frontend)}'
        )

    @pytest.mark.parametrize('role', ['tester', 'viewer'])
    def test_role_defaults_are_drawn_from_the_vocabulary(self, role):
        # A typo in a role default is silent: the string simply never matches a gate.
        vocabulary = _string_set(PERMISSION_ROUTES.read_text(), '_ALL_PERMISSIONS = [')
        unknown = ROLE_DEFAULT_PERMISSIONS[role] - vocabulary
        assert not unknown, f'{role} defaults name permissions that do not exist: {sorted(unknown)}'

    def test_admin_is_absent_from_the_role_table(self):
        # Admin short-circuits ahead of the table; listing it would be a fourth copy of the
        # vocabulary to keep in step.
        assert 'admin' not in ROLE_DEFAULT_PERMISSIONS

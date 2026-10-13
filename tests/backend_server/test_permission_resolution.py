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

3. **The editable role table** — role defaults live in public.role_permissions (seeded by
   migration 20260929a), are read through a TTL cache, and are edited through
   PUT /server/roles/<role>.
"""

import json
import re
from pathlib import Path

import pytest
from flask import Flask, request

from backend_server.src.lib import auth_middleware
from backend_server.src.lib.auth_middleware import principal_holds_permission
from backend_server.src.routes import server_permissions_routes

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTH_TS = REPO_ROOT / 'frontend' / 'src' / 'types' / 'auth.ts'
PERMISSION_ROUTES = REPO_ROOT / 'backend_server' / 'src' / 'routes' / 'server_permissions_routes.py'
# Canonical fresh-install seed of every editable role (the migrations reach the same state).
ROLE_SCHEMA = REPO_ROOT / 'setup' / 'db' / 'schema' / '053_role_catalog.sql'
EDITABLE = ['manager', 'developer', 'tester', 'viewer']

_PERMISSION_RE = re.compile(r"'([a-z_]+(?:\.[a-z_]+)?:[a-z_]+)'")


def _seeded_role_defaults():
    """role -> permissions exactly as 053_role_catalog.sql seeds public.role_permissions."""
    rows = re.findall(r"\('(manager|developer|tester|viewer)', '(\[.*?\])'::jsonb\)",
                      ROLE_SCHEMA.read_text(encoding='utf-8'), re.S)
    return {role: json.loads(perms) for role, perms in rows}


@pytest.fixture(autouse=True)
def role_table(monkeypatch):
    """Serve the seeded role table instead of the database, with a cold cache per test."""
    table = _seeded_role_defaults()
    monkeypatch.setattr(auth_middleware, '_load_role_defaults', lambda: table)
    monkeypatch.setitem(auth_middleware._role_defaults_cache, 'value', None)
    auth_middleware.invalidate_role_defaults_cache()
    return table


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

    def test_a_team_never_grants(self):
        # TASK-31: teams.permissions is a ceiling. Being in a team whose ceiling lists a
        # permission gives nothing by itself.
        assert not _holds(
            'device_control:reboot',
            user_role='tester',
            user_team_ceiling=['device_control:reboot'],
        )

    def test_viewer_role_default(self):
        assert _holds('dashboard:view', user_role='viewer')

    def test_viewer_holds_nothing_it_was_not_given(self):
        assert not _holds('org.workspaces:create', user_role='viewer')


class TestTeamCeiling:
    """TASK-31: the team ceiling caps role defaults and grants; None means no limit."""

    def test_no_ceiling_is_no_limit(self):
        assert _holds('testcases:create', user_role='tester', user_team_ceiling=None)

    def test_ceiling_blocks_a_role_default(self):
        assert not _holds('testcases:create', user_role='tester', user_team_ceiling=['testcases:view'])

    def test_ceiling_keeps_what_it_lists(self):
        assert _holds('testcases:view', user_role='tester', user_team_ceiling=['testcases:view'])

    def test_ceiling_blocks_an_individual_grant(self):
        assert not _holds('org.workspaces:view', user_role='tester',
                          user_permissions=['org.workspaces:view'], user_team_ceiling=[])

    def test_grant_beyond_the_role_inside_the_ceiling(self):
        # Decision 6: a user grant beyond the role is fine inside the team ceiling.
        assert _holds('org.workspaces:view', user_role='tester',
                      user_permissions=['org.workspaces:view'],
                      user_team_ceiling=['org.workspaces:view', 'testcases:view'])

    def test_empty_ceiling_allows_nothing(self):
        assert not _holds('dashboard:view', user_role='viewer', user_team_ceiling=[])

    def test_admin_ignores_the_ceiling(self):
        assert _holds('settings.general:edit', user_role='admin', user_team_ceiling=[])

    @pytest.mark.parametrize('app_meta,expected', [
        ({}, None),                                          # token minted before the claim
        ({'team_ceiling': None}, None),
        ({'team_ceiling': ['a:view']}, ['a:view']),
        ({'team_permissions': ['a:view']}, None),            # the old grants claim is not read
    ])
    def test_claim(self, app_meta, expected):
        assert auth_middleware.team_ceiling_claim(app_meta) == expected


class TestTeamCap:
    """users_db.team_cap(): the Python twin of SQL public.team_cap()."""

    def _cap(self, *teams):
        from shared.src.lib.database.users_db import team_cap
        return team_cap(list(teams), 'permissions')

    def test_no_team_no_limit(self):
        assert self._cap() is None

    def test_union_of_teams(self):
        assert self._cap({'permissions': ['a:view']}, {'permissions': ['b:view']}) == ['a:view', 'b:view']

    def test_an_uncapped_team_lifts_the_limit(self):
        assert self._cap({'permissions': ['a:view']}, {'permissions': None}) is None

    def test_default_team_left_out_when_in_another(self):
        assert self._cap({'permissions': None, 'is_default': True}, {'permissions': ['a:view']}) == ['a:view']

    def test_default_team_counts_when_it_is_the_only_one(self):
        assert self._cap({'permissions': ['a:view'], 'is_default': True}) == ['a:view']


class TestDenials:
    """A denial beats every grant — for everyone but an admin."""

    def test_denial_beats_grant(self):
        assert not _holds(
            'testcases:delete',
            user_role='tester',
            user_denied_permissions=['testcases:delete'],
            user_permissions=['testcases:delete'],
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

    @pytest.mark.parametrize('role', EDITABLE)
    def test_seeded_role_defaults_are_drawn_from_the_vocabulary(self, role, role_table):
        # A typo in a role default is silent: the string simply never matches a gate.
        vocabulary = _string_set(PERMISSION_ROUTES.read_text(), '_ALL_PERMISSIONS = [')
        unknown = set(role_table[role]) - vocabulary
        assert not unknown, f'{role} defaults name permissions that do not exist: {sorted(unknown)}'

    def test_admin_is_absent_from_the_role_table(self, role_table):
        # Admin short-circuits ahead of the table; a row would be a copy of the vocabulary.
        assert set(role_table) == set(EDITABLE) == set(auth_middleware.EDITABLE_ROLES)

    @pytest.mark.parametrize('role', EDITABLE)
    def test_seeded_role_defaults_hold_no_admin_only_permission(self, role, role_table):
        # The Roles page refuses these for every role; the seed must not start out holding one.
        assert not set(role_table[role]) & auth_middleware.ADMIN_ONLY_PERMISSIONS

    def test_admin_only_permissions_are_in_the_vocabulary(self):
        vocabulary = _string_set(PERMISSION_ROUTES.read_text(), '_ALL_PERMISSIONS = [')
        assert auth_middleware.ADMIN_ONLY_PERMISSIONS <= vocabulary

    def test_the_migration_seeds_the_new_roles_like_the_schema(self, role_table):
        migration = (REPO_ROOT / 'setup' / 'db' / 'migrations' / '20260929c_role_catalog.sql').read_text(encoding='utf-8')
        rows = dict(re.findall(r"\('(manager|developer)', '(\[.*?\])'::jsonb\)", migration, re.S))
        for role in ('manager', 'developer'):
            assert sorted(json.loads(rows[role])) == sorted(role_table[role])

    def test_seeded_viewer_holds_only_view_permissions(self, role_table):
        assert role_table['viewer'] and all(p.endswith(':view') for p in role_table['viewer'])


class TestRoleDefaultsCache:
    """role_default_permissions(): TTL cache over the database, fail-closed without it."""

    def test_unreadable_table_with_nothing_cached_grants_nothing(self, monkeypatch):
        monkeypatch.setattr(auth_middleware, '_load_role_defaults', lambda: None)
        assert auth_middleware.role_default_permissions('tester') == set()

    def test_unreadable_table_keeps_the_last_good_copy(self, monkeypatch):
        assert 'testcases:create' in auth_middleware.role_default_permissions('tester')
        monkeypatch.setattr(auth_middleware, '_load_role_defaults', lambda: None)
        auth_middleware.invalidate_role_defaults_cache()
        assert 'testcases:create' in auth_middleware.role_default_permissions('tester')

    def test_edit_applies_after_invalidation(self, monkeypatch):
        assert _holds('dashboard:view', user_role='viewer')
        monkeypatch.setattr(auth_middleware, '_load_role_defaults', lambda: {'tester': [], 'viewer': []})
        auth_middleware.invalidate_role_defaults_cache()
        assert not _holds('dashboard:view', user_role='viewer')


class TestUpdateRoleRoute:
    """PUT /server/roles/<role> validation. The database write is stubbed."""

    @pytest.fixture
    def saved(self, monkeypatch):
        calls = []

        def fake_update(role, permissions, updated_by):
            calls.append((role, permissions, updated_by))
            return permissions

        monkeypatch.setattr(server_permissions_routes.role_permissions_db, 'update_role_permissions', fake_update)
        return calls

    def _put(self, role, body, user_role='admin'):
        app = Flask(__name__)
        with app.test_request_context(f'/server/roles/{role}', method='PUT', json=body):
            request.user_role = user_role
            request.user_id = 'auto_signed'
            response = server_permissions_routes.update_role(role)
            resp, status = response if isinstance(response, tuple) else (response, 200)
            return status, resp.get_json()

    def test_saves_tester_permissions(self, saved):
        status, body = self._put('tester', {'permissions': ['testcases:view', 'testcases:delete']})
        assert status == 200 and body['success']
        # Sorted, deduplicated; non-UUID principals (auto-sign, service) have no profile to reference.
        assert saved == [('tester', ['testcases:delete', 'testcases:view'], None)]

    def test_viewer_rejects_non_view_permissions(self, saved):
        status, body = self._put('viewer', {'permissions': ['testcases:view', 'testcases:edit']})
        assert status == 400 and 'testcases:edit' in body['error']
        assert saved == []

    def test_viewer_can_drop_a_view(self, saved):
        status, _ = self._put('viewer', {'permissions': ['dashboard:view']})
        assert status == 200
        assert saved == [('viewer', ['dashboard:view'], None)]

    def test_admin_permissions_are_not_editable(self, saved):
        status, _ = self._put('admin', {'permissions': []})
        assert status == 400 and saved == []

    def test_unknown_role(self, saved):
        status, _ = self._put('nonsense', {'permissions': []})
        assert status == 404 and saved == []

    @pytest.mark.parametrize('role', EDITABLE[:-1])
    def test_admin_only_permission_refused_for_every_role(self, saved, role):
        status, body = self._put(role, {'permissions': ['testcases:view', 'settings.general:edit']})
        assert status == 400 and 'settings.general:edit' in body['error']
        assert saved == []

    def test_preferred_name(self, saved, monkeypatch):
        names = []
        monkeypatch.setattr(server_permissions_routes.roles_db, 'update_display_name',
                            lambda role, name, by: names.append((role, name)) or True)
        status, body = self._put('developer', {'display_name': ' DevUser '})
        assert status == 200 and body['success']
        assert names == [('developer', 'DevUser')]
        assert saved == []  # permissions untouched

    def test_admin_preferred_name_is_editable(self, saved, monkeypatch):
        monkeypatch.setattr(server_permissions_routes.roles_db, 'update_display_name', lambda *a: True)
        status, _ = self._put('admin', {'display_name': 'SuperAdmin'})
        assert status == 200

    def test_blank_preferred_name_rejected(self, saved):
        status, _ = self._put('developer', {'display_name': '  '})
        assert status == 400

    def test_preferred_name_taken_by_another_role_is_a_conflict(self, saved, monkeypatch):
        def taken(role, name, by):
            raise ValueError(f"'{name}' is already the name of another role")
        monkeypatch.setattr(server_permissions_routes.roles_db, 'update_display_name', taken)
        status, _ = self._put('developer', {'display_name': 'Tester'})
        assert status == 409

    def test_empty_body_rejected(self, saved):
        status, _ = self._put('tester', {})
        assert status == 400

    def test_unknown_permission_rejected(self, saved):
        status, body = self._put('tester', {'permissions': ['testcases:fly']})
        assert status == 400 and 'testcases:fly' in body['error']
        assert saved == []

    def test_tester_cannot_edit_roles(self, saved):
        status, _ = self._put('tester', {'permissions': []}, user_role='tester')
        assert status == 403 and saved == []

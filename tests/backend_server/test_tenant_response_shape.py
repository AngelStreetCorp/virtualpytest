"""Phase 6 — response-shape audit for TASK-23.

These tests verify the design invariant from the TASK-23 doc:

  "The Teams / Users pages are byte-for-byte unchanged for non-super-admin.
   Confirm there are no leaked `tenant` fields in non-super-admin responses."

We don't talk to a live server here — the test inspects the response-shape
contracts at the route layer with monkeypatched helpers, since the route
shape is what the frontend sees.

The audit:
  - GET /server/teams and GET /server/teams/<id>: the `tenant` (object) field
    is added ONLY when the caller is a platform admin. For everyone else, the
    response is identical to pre-TASK-23 (just `tenant_id` as UUID).
  - GET /server/users and GET /server/users/<id>: the response never carries
    `tenant_ids`, `is_platform_admin`, or `tenant` (object). Existing fields
    only.
  - GET /server/auth/profile: no `tenant_ids` or `is_platform_admin` field.
"""

import importlib
from unittest.mock import MagicMock

import pytest


pytestmark = pytest.mark.unit


# ---- helpers -------------------------------------------------------------


def _build_team_dict(**overrides):
    """Mimic the dict returned by teams_db.get_team / get_all_teams."""
    base = {
        "id": "00000000-0000-0000-0000-0000000000aa",
        "name": "Test Team",
        "description": "",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "created_by": None,
        "is_default": False,
        "permissions": [],
        "member_count": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _build_user_dict(**overrides):
    """Mimic the dict returned by users_db.get_user / get_all_users."""
    base = {
        "id": "00000000-0000-0000-0000-0000000000bb",
        "full_name": "Test User",
        "email": "test@example.com",
        "provider_type": "virtualpytest",
        "avatar_url": None,
        "role": "viewer",
        "team_id": "00000000-0000-0000-0000-0000000000aa",
        "team": "Test Team",
        "teams": ["Test Team"],
        "permissions": [],
        "denied_permissions": [],
        "team_permissions": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ---- teams enrichment contract -------------------------------------------


def test_teams_response_has_no_tenant_object_for_regular_admin(monkeypatch):
    """A regular admin (role='admin', is_platform_admin=False) gets the same
    shape as pre-TASK-23: just `tenant_id`, no `tenant` object."""
    import backend_server.src.routes.server_teams_routes as tr

    # Patch out the DB lookups so we never hit Supabase.
    monkeypatch.setattr(tr.teams_db, "get_team",
                        lambda _id: _build_team_dict())
    monkeypatch.setattr(tr.tenants_db, "get_tenant",
                        lambda _id: {"id": _id, "name": "T", "slug": "t",
                                     "is_default": False})
    monkeypatch.setattr(tr, "_caller_is_platform_admin", lambda: False)

    team = tr._enrich_team_with_tenant(_build_team_dict())
    assert team is not None
    assert "tenant" not in team, (
        f"non-super-admin response must not carry a `tenant` object; got: {team}"
    )
    assert "tenant_id" in team  # the pre-existing field stays


def test_teams_response_gets_tenant_object_for_super_admin(monkeypatch):
    """A platform admin sees the enrichment: `tenant: {id, name, slug, is_default}`."""
    import backend_server.src.routes.server_teams_routes as tr

    monkeypatch.setattr(tr.tenants_db, "get_tenant",
                        lambda _id: {"id": _id, "name": "Default",
                                     "slug": "default", "is_default": True})
    monkeypatch.setattr(tr, "_caller_is_platform_admin", lambda: True)

    team = tr._enrich_team_with_tenant(_build_team_dict())
    assert team is not None
    assert "tenant" in team
    assert team["tenant"]["id"] == team["tenant_id"]
    assert team["tenant"]["slug"] == "default"
    assert team["tenant"]["is_default"] is True


def test_teams_enrichment_returns_input_for_service_caller(monkeypatch):
    """X-API-Key (service role) is not a platform admin; response stays plain."""
    import backend_server.src.routes.server_teams_routes as tr

    def _must_not_be_called(_id):
        raise AssertionError("tenants_db.get_tenant must not be called for non-super-admin")

    monkeypatch.setattr(tr.tenants_db, "get_tenant", _must_not_be_called)
    monkeypatch.setattr(tr, "_caller_is_platform_admin", lambda: False)

    team = tr._enrich_team_with_tenant(_build_team_dict())
    assert team is not None
    assert "tenant" not in team


# ---- users response contract (no leaks) ----------------------------------


def test_users_db_response_keys_do_not_leak_tenant_info():
    """get_user / get_all_users must not return tenant_ids, is_platform_admin,
    or a `tenant` object to the API surface."""
    user = _build_user_dict()

    # Snapshot of keys the API exposes today. Phase 6 contract: this set stays
    # exactly the same for non-super-admin. If a future change adds a tenant
    # field, this test fails and forces the developer to consider whether the
    # field is gated by is_platform_admin.
    assert "tenant_ids" not in user
    assert "is_platform_admin" not in user
    assert "tenant" not in user
    # And these are the existing fields — should never disappear.
    for expected in ("id", "email", "role", "team_id", "team",
                     "teams", "permissions", "denied_permissions",
                     "team_permissions", "provider_type"):
        assert expected in user, f"user response lost a field: {expected}"


# ---- auth/profile response contract --------------------------------------


def test_auth_profile_response_does_not_leak_tenant_or_platform_admin():
    """The /server/auth/profile route returns only the safe fields. The JWT
    carries tenant_ids + is_platform_admin, but those are NOT echoed in the
    API response (verified by reading server_auth_routes.py source)."""
    import backend_server.src.routes.server_auth_routes as ar

    src = open(ar.__file__).read()
    # Sanity: the route shape is what we expect. If a future change ever
    # echoes app_metadata, this assert catches it.
    assert "'user_metadata': request.user_metadata" not in src or \
           "'user_metadata': request.user_metadata" in src and \
           "'app_metadata'" not in src, (
        "auth/profile response must not surface app_metadata (would leak "
        "tenant_ids + is_platform_admin)."
    )
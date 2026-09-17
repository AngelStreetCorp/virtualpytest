"""Provisioning defaults in shared/src/lib/database/users_db.upsert_user().

Two defaults an external system (dmacp, …) relies on, asserted on the exact payloads
written to `profiles` and `auth.users` — no network, no Supabase:

- `full_name` falls back to the email's local part, is never allowed to overwrite a name
  someone already chose, and is mirrored into auth user_metadata so Supabase Studio's
  "Display name" column shows it too (that column reads raw_user_meta_data, not profiles).
- `provider_type` is 'virtualpytest' unless the caller names its own platform, and an
  update only rewrites it when the caller actually sent one.

Run: pytest tests/shared/test_users_provisioning_defaults.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.database import users_db  # noqa: E402

EMAIL = "marie.dupont@example.com"


class _FakeTable:
    def __init__(self, recorder, name, responses):
        self._recorder, self._name, self._payload = recorder, name, None
        self._responses = responses

    def update(self, payload):
        self._payload = payload
        return self

    def insert(self, payload):
        self._payload = payload
        return self

    def select(self, *_a, **_kw):
        return self

    def eq(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    def single(self, *_a, **_kw):
        self._single = True
        return self

    def execute(self):
        self._recorder.append((self._name, self._payload))
        data = self._responses.get(self._name, [])
        if getattr(self, "_single", False):
            return type("R", (), {"data": data[0] if data else None})()
        return type("R", (), {"data": data})()


class _FakeAdmin:
    """Just enough of the supabase client for upsert_user's write path."""

    def __init__(self):
        self.writes = []
        self.created = []
        self.responses = {}  # table name -> rows the next execute() returns
        outer = self

        class _AuthAdmin:
            def create_user(self, payload):
                outer.created.append(payload)
                return {"id": "new-uuid"}

            def update_user_by_id(self, uid, payload):
                outer.writes.append(("auth", {"id": uid, **payload}))

        self.auth = type("A", (), {"admin": _AuthAdmin()})()

    def table(self, name):
        return _FakeTable(self.writes, name, self.responses)


@pytest.fixture
def admin(monkeypatch):
    fake = _FakeAdmin()
    monkeypatch.setattr(users_db, "_admin_or_raise", lambda: fake)
    return fake


def _profile_write(admin):
    """The single `profiles` payload upsert_user wrote."""
    writes = [payload for table, payload in admin.writes if table == "profiles"]
    assert len(writes) == 1, writes
    return writes[0]


def _absent(monkeypatch):
    monkeypatch.setattr(users_db, "get_user_by_email", lambda _e: None)


def _existing(monkeypatch, **overrides):
    profile = {"id": "uuid-1", "email": EMAIL, "full_name": "", "role": "tester",
               "team_id": None, "team": None, "provider_type": "virtualpytest"}
    profile.update(overrides)
    monkeypatch.setattr(users_db, "get_user_by_email", lambda _e: profile)
    return profile


# --------------------------------------------------------------- default_full_name

@pytest.mark.parametrize("email,expected", [
    ("marie.dupont@example.com", "marie.dupont"),
    ("jean.martin@sub.example.com", "jean.martin"),
    ("nodomain", "nodomain"),
    ("", ""),
])
def test_default_full_name(email, expected):
    assert users_db.default_full_name(email) == expected


# ------------------------------------------------------------------------- create

def test_create_defaults_name_to_email_local_part(admin, monkeypatch):
    _absent(monkeypatch)
    result = users_db.upsert_user(email=EMAIL, password="a strong password")
    assert _profile_write(admin)["full_name"] == "marie.dupont"
    assert result["full_name"] == "marie.dupont"


def test_create_writes_the_name_to_auth_user_metadata(admin, monkeypatch):
    """Supabase Studio's Display name column reads raw_user_meta_data, not profiles."""
    _absent(monkeypatch)
    users_db.upsert_user(email=EMAIL, password="a strong password")
    assert admin.created[0]["user_metadata"] == {"display_name": "marie.dupont",
                                                 "full_name": "marie.dupont"}


def test_reset_updates_auth_user_metadata_with_the_password(admin, monkeypatch):
    _existing(monkeypatch, full_name="")
    users_db.upsert_user(email=EMAIL, password="the new password")
    auth_writes = [p for t, p in admin.writes if t == "auth"]
    assert len(auth_writes) == 1, auth_writes
    assert auth_writes[0]["password"] == "the new password"
    assert auth_writes[0]["user_metadata"]["display_name"] == "marie.dupont"


def test_reset_that_changes_no_name_sends_no_metadata(admin, monkeypatch):
    _existing(monkeypatch, full_name="Marie D.")
    users_db.upsert_user(email=EMAIL, password="the new password")
    auth_writes = [p for t, p in admin.writes if t == "auth"]
    assert len(auth_writes) == 1, auth_writes
    assert "user_metadata" not in auth_writes[0]


def test_create_keeps_an_explicit_name(admin, monkeypatch):
    _absent(monkeypatch)
    result = users_db.upsert_user(email=EMAIL, password="a strong password",
                                  full_name="Marie Dupont")
    assert _profile_write(admin)["full_name"] == "Marie Dupont"
    assert result["full_name"] == "Marie Dupont"


def test_create_defaults_provider_type_to_virtualpytest(admin, monkeypatch):
    _absent(monkeypatch)
    result = users_db.upsert_user(email=EMAIL, password="a strong password")
    assert _profile_write(admin)["provider_type"] == "virtualpytest"
    assert result["provider_type"] == "virtualpytest"


def test_create_records_the_calling_platform(admin, monkeypatch):
    _absent(monkeypatch)
    result = users_db.upsert_user(email=EMAIL, password="a strong password",
                                  provider_type="dmacp")
    assert _profile_write(admin)["provider_type"] == "dmacp"
    assert result["provider_type"] == "dmacp"


# ------------------------------------------------------------------------- update

def test_reset_backfills_a_missing_name(admin, monkeypatch):
    _existing(monkeypatch, full_name="")
    result = users_db.upsert_user(email=EMAIL, password="the new password")
    assert _profile_write(admin)["full_name"] == "marie.dupont"
    assert result["action"] == "updated"


def test_reset_never_overwrites_a_chosen_name(admin, monkeypatch):
    _existing(monkeypatch, full_name="Marie D.")
    result = users_db.upsert_user(email=EMAIL, password="the new password")
    assert not [p for t, p in admin.writes if t == "profiles"], admin.writes
    assert result["full_name"] == "Marie D."


def test_reset_leaves_provider_type_alone_when_not_sent(admin, monkeypatch):
    _existing(monkeypatch, full_name="Marie D.", provider_type="dmacp")
    result = users_db.upsert_user(email=EMAIL, password="the new password")
    assert result["provider_type"] == "dmacp"


def test_reset_reassigns_provider_type_when_sent(admin, monkeypatch):
    _existing(monkeypatch, full_name="Marie D.", provider_type="virtualpytest")
    result = users_db.upsert_user(email=EMAIL, password="the new password",
                                  provider_type="dmacp")
    assert _profile_write(admin)["provider_type"] == "dmacp"
    assert result["provider_type"] == "dmacp"


def test_create_reports_the_default_team_it_landed_in(admin, monkeypatch):
    """handle_new_user() puts a new user in the default team — say so.

    Reporting `"team": null` reads as "no team" when the person is in fact in the
    default one, which is the same lie BUG-0077 fixed for the `group` path.
    """
    _absent(monkeypatch)
    admin.responses["profiles"] = [{"id": "new-uuid", "team_id": "team-uuid"}]
    admin.responses["teams"] = [{"name": "Default Team"}]
    result = users_db.upsert_user(email=EMAIL, password="a strong password")
    assert result["team"] == "Default Team"


def test_blank_provider_type_is_rejected(admin, monkeypatch):
    _absent(monkeypatch)
    with pytest.raises(ValueError):
        users_db.upsert_user(email=EMAIL, password="a strong password", provider_type="   ")

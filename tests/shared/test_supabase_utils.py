"""Tests for shared/src/lib/utils/supabase_utils.py::get_db_key_role (TASK-10).

get_db_key_role() is the per-node rollout signal: it reports which Postgres role
the DB client runs as, preferring the service_role key over the anon key, and
understands both the new sb_publishable_/sb_secret_ keys and legacy eyJ JWTs.
"""
import base64
import json
import os

import pytest

# supabase_utils imports the real `supabase` package at module load; skip where
# it is not installed (the CI DB suite has it).
pytest.importorskip("supabase")

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
import sys  # noqa: E402
sys.path.insert(0, _repo_root)

from shared.src.lib.utils.supabase_utils import get_db_key_role  # noqa: E402


def _make_jwt(role: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.signature"


@pytest.fixture(autouse=True)
def _clear_keys(monkeypatch):
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)


def test_no_keys_returns_none():
    assert get_db_key_role() == "none"


def test_new_publishable_key_is_anon(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_publishable_test_key_000000000000")
    assert get_db_key_role() == "anon"


def test_new_secret_key_is_service_role(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_deadbeef")
    assert get_db_key_role() == "service_role"


def test_service_role_key_preferred_over_anon(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_publishable_test_key_000000000000")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_y")
    assert get_db_key_role() == "service_role"


def test_legacy_jwt_anon(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", _make_jwt("anon"))
    assert get_db_key_role() == "anon"


def test_legacy_jwt_service_role(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", _make_jwt("service_role"))
    assert get_db_key_role() == "service_role"


def test_unrecognized_key_is_unknown(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "garbage-not-a-key")
    assert get_db_key_role() == "unknown"

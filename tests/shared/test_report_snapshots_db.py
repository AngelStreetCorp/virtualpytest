"""
Unit tests for shared/src/lib/database/report_snapshots_db.py (TASK-49 S1).

A fake supabase client is wired in by monkeypatching report_snapshots_db.get_supabase
to return a MagicMock chain. The chain is constructed so every .table(...).select(...)
.insert(...).update(...).eq(...).is_(...).gt(...).or_(...).order(...).limit(...).execute()
call returns a captured result object.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from shared.src.lib.database import report_snapshots_db


TEAM = "11111111-1111-1111-1111-111111111111"
OTHER_TEAM = "22222222-2222-2222-2222-222222222222"
SNAPSHOT_ID = "33333333-3333-3333-3333-333333333333"
SCRIPT_RESULT_ID = "44444444-4444-4444-4444-444444444444"
SERVER_NAME = "vpt-test"
KEY_HASH = "a" * 64
DELETE_KEY_HASH = "b" * 64


class FakeQueryChain:
    """Mimics a supabase-py PostgrestQueryBuilder.

    Records kwargs of .eq() / .is_() / .gt() / .or_() / .order() / .limit() so
    tests can assert on the filter chain, and short-circuits to .execute().
    """

    def __init__(self, result: MagicMock):
        self._result = result
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str, args, kwargs):
        self.calls.append((name, args, kwargs))
        return self

    def select(self, *args, **kwargs):
        return self._record("select", args, kwargs)

    def insert(self, *args, **kwargs):
        return self._record("insert", args, kwargs)

    def update(self, *args, **kwargs):
        return self._record("update", args, kwargs)

    def eq(self, *args, **kwargs):
        return self._record("eq", args, kwargs)

    def neq(self, *args, **kwargs):
        return self._record("neq", args, kwargs)

    def is_(self, *args, **kwargs):
        return self._record("is_", args, kwargs)

    def gt(self, *args, **kwargs):
        return self._record("gt", args, kwargs)

    def lt(self, *args, **kwargs):
        return self._record("lt", args, kwargs)

    def in_(self, *args, **kwargs):
        return self._record("in_", args, kwargs)

    def lte(self, *args, **kwargs):
        return self._record("lte", args, kwargs)

    @property
    def not_(self):
        return self._record("not_", (), {})

    def or_(self, *args, **kwargs):
        return self._record("or_", args, kwargs)

    def order(self, *args, **kwargs):
        return self._record("order", args, kwargs)

    def limit(self, *args, **kwargs):
        return self._record("limit", args, kwargs)

    def range(self, *args, **kwargs):
        return self._record("range", args, kwargs)

    def execute(self):
        return self._record("execute", (), {})._result


def _wire_supabase(rows):
    """Build a fake supabase client. `rows` is the payload execute() returns."""
    result = MagicMock()
    result.data = rows
    chain = FakeQueryChain(result)
    sb = MagicMock()
    sb.table.return_value = chain
    report_snapshots_db.get_supabase = lambda: sb
    return sb, chain


# --------------------------------------------------------------- create_snapshot


def test_create_snapshot_inserts_expected_row(monkeypatch):
    sb, chain = _wire_supabase([{"id": SNAPSHOT_ID}])
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    out = report_snapshots_db.create_snapshot(
        SNAPSHOT_ID,
        TEAM,
        SCRIPT_RESULT_ID,
        SERVER_NAME,
        "55555555-5555-5555-5555-555555555555",
        KEY_HASH,
        DELETE_KEY_HASH,
        None,
        "shared-snapshots/abc/",
        True,
        1024,
        expires_at,
    )
    assert out == {"id": SNAPSHOT_ID}
    sb.table.assert_called_with("report_snapshots")

    insert_call = next(c for c in chain.calls if c[0] == "insert")
    row = insert_call[1][0]
    assert row["id"] == SNAPSHOT_ID
    assert row["team_id"] == TEAM
    assert row["script_result_id"] == SCRIPT_RESULT_ID
    assert row["server_name"] == SERVER_NAME
    assert row["key_hash"] == KEY_HASH
    assert row["delete_key_hash"] == DELETE_KEY_HASH
    assert row["password_hash"] is None
    assert row["storage_prefix"] == "shared-snapshots/abc/"
    assert row["include_video"] is True
    assert row["size_bytes"] == 1024
    assert row["expires_at"] == expires_at.isoformat()


def test_create_snapshot_returns_none_on_exception(monkeypatch):
    def boom():
        raise RuntimeError("db down")
    report_snapshots_db.get_supabase = boom
    out = report_snapshots_db.create_snapshot(
        SNAPSHOT_ID, TEAM, SCRIPT_RESULT_ID, SERVER_NAME, None, KEY_HASH,
        DELETE_KEY_HASH, None, "p/", True, 0,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    assert out is None


# ----------------------------------------------------------------- get_snapshot


def test_get_snapshot_filters_by_team_and_id():
    sb, chain = _wire_supabase([{"id": SNAPSHOT_ID, "team_id": TEAM}])
    out = report_snapshots_db.get_snapshot(TEAM, SNAPSHOT_ID)
    assert out == {"id": SNAPSHOT_ID, "team_id": TEAM}

    eq_calls = [(name, args) for (name, args, _) in chain.calls if name == "eq"]
    assert ("eq", ("team_id", TEAM)) in eq_calls
    assert ("eq", ("id", SNAPSHOT_ID)) in eq_calls


def test_get_snapshot_returns_none_on_exception():
    report_snapshots_db.get_supabase = lambda: (_ for _ in ()).throw(RuntimeError("kaboom"))
    assert report_snapshots_db.get_snapshot(TEAM, SNAPSHOT_ID) is None


# ---------------------------------------------------------------- list_snapshots


def test_list_snapshots_never_returns_hash_fields_and_sets_has_password():
    rows = [
        {
            "id": SNAPSHOT_ID,
            "team_id": TEAM,
            "script_result_id": SCRIPT_RESULT_ID,
            "server_name": SERVER_NAME,
            "created_by": "user-1",
            "created_at": "2026-10-04T12:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "revoked_at": None,
            "purged_at": None,
            "include_video": True,
            "size_bytes": 2048,
            "view_count": 3,
            "last_viewed_at": "2026-10-04T13:00:00+00:00",
            "password_hash": "$argon2id$something",
        },
        {
            "id": "other-snap",
            "team_id": TEAM,
            "script_result_id": SCRIPT_RESULT_ID,
            "server_name": SERVER_NAME,
            "created_by": "user-2",
            "created_at": "2026-10-03T12:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "revoked_at": None,
            "purged_at": None,
            "include_video": False,
            "size_bytes": 1024,
            "view_count": 0,
            "last_viewed_at": None,
            "password_hash": None,
        },
    ]
    _wire_supabase(rows)
    out = report_snapshots_db.list_snapshots(TEAM, SCRIPT_RESULT_ID, active_only=True)

    assert len(out) == 2
    for row in out:
        assert "key_hash" not in row
        assert "delete_key_hash" not in row
        assert "password_hash" not in row
    assert out[0]["has_password"] is True
    assert out[1]["has_password"] is False


def test_list_snapshots_filters_active_only():
    _wire_supabase([])
    chain = report_snapshots_db.get_supabase().table.return_value
    report_snapshots_db.list_snapshots(TEAM, SCRIPT_RESULT_ID, active_only=True)

    call_names = [name for (name, _, _) in chain.calls]
    assert "is_" in call_names  # revoked_at IS NULL
    assert "gt" in call_names   # expires_at > now

    is_call = next(c for c in chain.calls if c[0] == "is_")
    assert is_call[1] == ("revoked_at", "null")

    gt_call = next(c for c in chain.calls if c[0] == "gt")
    assert gt_call[1][0] == "expires_at"
    # second arg is the now-iso string; we just check it's a parseable iso
    datetime.fromisoformat(gt_call[1][1])


def test_list_snapshots_returns_empty_on_exception():
    def boom():
        raise RuntimeError("db down")
    report_snapshots_db.get_supabase = boom
    assert report_snapshots_db.list_snapshots(TEAM, SCRIPT_RESULT_ID) == []


# ----------------------------------------------------- get_snapshot_by_*_key_hash


def test_get_snapshot_by_key_hash_uses_no_team_filter():
    _wire_supabase([{"id": SNAPSHOT_ID}])
    out = report_snapshots_db.get_snapshot_by_key_hash(KEY_HASH)
    assert out == {"id": SNAPSHOT_ID}

    chain = report_snapshots_db.get_supabase().table.return_value
    eq_calls = [(name, args) for (name, args, _) in chain.calls if name == "eq"]
    assert eq_calls == [("eq", ("key_hash", KEY_HASH))]


def test_get_snapshot_by_delete_key_hash_uses_no_team_filter():
    _wire_supabase([{"id": SNAPSHOT_ID}])
    out = report_snapshots_db.get_snapshot_by_delete_key_hash(DELETE_KEY_HASH)
    assert out == {"id": SNAPSHOT_ID}

    chain = report_snapshots_db.get_supabase().table.return_value
    eq_calls = [(name, args) for (name, args, _) in chain.calls if name == "eq"]
    assert eq_calls == [("eq", ("delete_key_hash", DELETE_KEY_HASH))]


# --------------------------------------------------------------- revoke_snapshot


def test_revoke_snapshot_filters_by_team_and_only_unrevoked():
    _wire_supabase([{"id": SNAPSHOT_ID}])
    ok = report_snapshots_db.revoke_snapshot(TEAM, SNAPSHOT_ID)
    assert ok is True

    chain = report_snapshots_db.get_supabase().table.return_value
    eq_calls = [(name, args) for (name, args, _) in chain.calls if name == "eq"]
    assert ("eq", ("team_id", TEAM)) in eq_calls
    assert ("eq", ("id", SNAPSHOT_ID)) in eq_calls

    is_calls = [(name, args) for (name, args, _) in chain.calls if name == "is_"]
    assert ("is_", ("revoked_at", "null")) in is_calls


def test_revoke_snapshot_by_id_does_not_filter_by_team():
    _wire_supabase([{"id": SNAPSHOT_ID}])
    ok = report_snapshots_db.revoke_snapshot_by_id(SNAPSHOT_ID)
    assert ok is True

    chain = report_snapshots_db.get_supabase().table.return_value
    eq_calls = [(name, args) for (name, args, _) in chain.calls if name == "eq"]
    # only id filter, no team filter on the delete-key path
    assert eq_calls == [("eq", ("id", SNAPSHOT_ID))]


def test_revoke_snapshot_returns_false_on_exception():
    def boom():
        raise RuntimeError("db down")
    report_snapshots_db.get_supabase = boom
    assert report_snapshots_db.revoke_snapshot(TEAM, SNAPSHOT_ID) is False


# ------------------------------------------------------------------ record_view


def test_record_view_swallows_exceptions():
    """record_view is best effort and must never raise."""

    def boom():
        raise RuntimeError("db down")
    report_snapshots_db.get_supabase = boom
    # No assertion: the contract is "never raises".
    report_snapshots_db.record_view(SNAPSHOT_ID)


def test_record_view_reads_then_writes():
    sb, chain = _wire_supabase([{"view_count": 7}])
    # First .execute() returns the select result, then the update chain calls execute() again.
    # We reset calls after the select reads; track updates separately.
    report_snapshots_db.record_view(SNAPSHOT_ID)

    select_calls = [c for c in chain.calls if c[0] == "select"]
    update_calls = [c for c in chain.calls if c[0] == "update"]
    assert select_calls, "should have read view_count first"
    assert update_calls, "should have written the new view_count"

    update_row = update_calls[0][1][0]
    assert update_row["view_count"] == 8
    assert "last_viewed_at" in update_row


# ------------------------------------------------------------------ list_purgeable


def test_list_purgeable_filters_by_server_and_purgeable():
    rows = [{"id": "abcd", "server_name": SERVER_NAME}]
    _wire_supabase(rows)
    out = report_snapshots_db.list_purgeable(SERVER_NAME, limit=50)
    assert out == rows

    chain = report_snapshots_db.get_supabase().table.return_value
    eq_calls = [(name, args) for (name, args, _) in chain.calls if name == "eq"]
    assert ("eq", ("server_name", SERVER_NAME)) in eq_calls
    is_calls = [(name, args) for (name, args, _) in chain.calls if name == "is_"]
    assert ("is_", ("purged_at", "null")) in is_calls

    or_calls = [c for c in chain.calls if c[0] == "or_"]
    assert or_calls, "expected an .or_ filter (revoked_at IS NOT NULL OR expires_at < now)"
    or_filter = or_calls[0][1][0]
    assert "revoked_at.not.is.null" in or_filter
    assert "expires_at.lt." in or_filter

    limit_call = next(c for c in chain.calls if c[0] == "limit")
    assert limit_call[1] == (50,)
    order_call = next(c for c in chain.calls if c[0] == "order")
    assert order_call[1] == ("created_at",) and order_call[2].get("desc") is False  # oldest first


# -------------------------------------------------------------------- mark_purged


def test_mark_purged_sets_purged_at():
    _wire_supabase([{"id": SNAPSHOT_ID}])
    ok = report_snapshots_db.mark_purged(SNAPSHOT_ID)
    assert ok is True

    chain = report_snapshots_db.get_supabase().table.return_value
    update_call = next(c for c in chain.calls if c[0] == "update")
    assert "purged_at" in update_call[1][0]


# ----------------------------------------------------------------- team_live_bytes


def test_team_live_bytes_sums_size_bytes():
    rows = [{"size_bytes": 100}, {"size_bytes": 250}, {"size_bytes": 50}]
    _wire_supabase(rows)
    total = report_snapshots_db.team_live_bytes(TEAM)
    assert total == 400

    chain = report_snapshots_db.get_supabase().table.return_value
    eq_calls = [(name, args) for (name, args, _) in chain.calls if name == "eq"]
    assert ("eq", ("team_id", TEAM)) in eq_calls
    is_calls = [(name, args) for (name, args, _) in chain.calls if name == "is_"]
    assert ("is_", ("purged_at", "null")) in is_calls
    # Revoked and expired rows count until the sweeper purges them: only purged_at filters.
    assert ("is_", ("revoked_at", "null")) not in is_calls
    assert not [c for c in chain.calls if c[0] == "gt"]


def test_team_live_bytes_ignores_non_int():
    rows = [{"size_bytes": 100}, {"size_bytes": "not-a-number"}, {"size_bytes": 25}]
    _wire_supabase(rows)
    assert report_snapshots_db.team_live_bytes(TEAM) == 125


def test_team_live_bytes_returns_zero_on_exception():
    def boom():
        raise RuntimeError("db down")
    report_snapshots_db.get_supabase = boom
    assert report_snapshots_db.team_live_bytes(TEAM) == 0

# ------------------------------------------------------- list_team_snapshots


def _team_row(**over):
    row = {"id": SNAPSHOT_ID, "team_id": TEAM, "script_result_id": SCRIPT_RESULT_ID, "server_name": SERVER_NAME,
           "created_by": None, "created_at": "2026-10-04T12:00:00+00:00", "expires_at": "2099-01-01T00:00:00+00:00",
           "revoked_at": None, "purged_at": None, "include_video": True, "size_bytes": 1, "view_count": 0,
           "last_viewed_at": None, "password_hash": "$h"}
    row.update(over)
    return row


def _names(chain):
    return [c[0] for c in chain.calls]


def test_list_team_snapshots_always_filters_team_orders_and_hides_hashes():
    for status in ("active", "expired", "revoked", "all"):
        _wire_supabase([_team_row()])
        chain = report_snapshots_db.get_supabase().table.return_value
        out = report_snapshots_db.list_team_snapshots(TEAM, status)
        assert ("eq", ("team_id", TEAM), {}) in chain.calls
        assert ("order", ("created_at",), {"desc": True}) in chain.calls
        assert out[0]["has_password"] is True and "password_hash" not in out[0]
        select = next(c for c in chain.calls if c[0] == "select")[1][0]
        assert "key_hash" not in select.replace("password_hash", "") and "delete_key_hash" not in select
        assert "script_result_id" in select and "purged_at" in select and "server_name" in select


def test_list_team_snapshots_status_filters():
    _wire_supabase([])
    chain = report_snapshots_db.get_supabase().table.return_value
    report_snapshots_db.list_team_snapshots(TEAM, "active")
    assert ("is_", ("revoked_at", "null"), {}) in chain.calls and "gt" in _names(chain)

    _wire_supabase([])
    chain = report_snapshots_db.get_supabase().table.return_value
    report_snapshots_db.list_team_snapshots(TEAM, "expired")
    assert ("is_", ("revoked_at", "null"), {}) in chain.calls and "lte" in _names(chain)

    _wire_supabase([])
    chain = report_snapshots_db.get_supabase().table.return_value
    report_snapshots_db.list_team_snapshots(TEAM, "revoked")
    assert "not_" in _names(chain) and ("is_", ("revoked_at", "null"), {}) in chain.calls
    assert "gt" not in _names(chain) and "lte" not in _names(chain)

    _wire_supabase([])
    chain = report_snapshots_db.get_supabase().table.return_value
    report_snapshots_db.list_team_snapshots(TEAM, "all", limit=5)
    assert "is_" not in _names(chain) and ("limit", (5,), {}) in chain.calls


def test_list_team_snapshots_returns_empty_on_exception():
    def boom():
        raise RuntimeError("db down")
    report_snapshots_db.get_supabase = boom
    assert report_snapshots_db.list_team_snapshots(TEAM) == []


def test_get_script_summaries_is_one_team_scoped_in_query():
    _wire_supabase([{"id": "r1", "script_name": "zap", "device_name": "d", "host_name": "h",
                     "started_at": "T", "html_report_r2_url": "u"}])
    chain = report_snapshots_db.get_supabase().table.return_value
    out = report_snapshots_db.get_script_summaries(TEAM, ["r1", "r1", "r2", None])
    assert out["r1"]["script_name"] == "zap" and out["r1"]["report_url"] == "u"
    assert ("eq", ("team_id", TEAM), {}) in chain.calls
    assert ("in_", ("id", ["r1", "r2"]), {}) in chain.calls
    assert report_snapshots_db.get_script_summaries(TEAM, []) == {}


def test_get_profile_names_prefers_full_name_then_email():
    _wire_supabase([{"id": "u1", "full_name": "Ann", "email": "a@x"}, {"id": "u2", "full_name": "", "email": "b@x"}])
    assert report_snapshots_db.get_profile_names(["u1", "u2"]) == {"u1": "Ann", "u2": "b@x"}

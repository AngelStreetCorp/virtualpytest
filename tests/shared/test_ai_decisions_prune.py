"""prune_decisions (TASK-47 follow-up): shared/src/lib/database/ai_decisions_db.py.

Fake supabase client (delete + eq + lt), no network.

Run: pytest tests/shared/test_ai_decisions_prune.py -v
"""
import os
import sys
from datetime import datetime, timezone

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from shared.src.lib.database import ai_decisions_db  # noqa: E402


class FakeDeleteQuery:
    """Records the delete / eq / lt chain and the cutoff used, then deletes matching rows."""

    def __init__(self, rows, now):
        self.rows = rows
        self.now = now
        self.ops = []

    def eq(self, col, val):
        self.ops.append(("eq", col, val))
        return self

    def lt(self, col, val):
        self.ops.append(("lt", col, val))
        return self

    def execute(self):
        class R:
            pass

        out = R()
        keep = []
        deleted = []
        for r in self.rows:
            ok = True
            for kind, col, val in self.ops:
                if kind == "eq" and r.get(col) != val:
                    ok = False
                    break
                if kind == "lt" and not (r.get(col) and r.get(col) < val):
                    ok = False
                    break
            if ok:
                deleted.append(r)
            else:
                keep.append(r)
        self.rows[:] = keep
        out.data = deleted
        return out


class FakeTable:
    def __init__(self, rows, now):
        self.rows = rows
        self.now = now
        self.last_delete = None

    def delete(self):
        q = FakeDeleteQuery(self.rows, self.now)
        self.last_delete = q
        return q


def _row(i, *, team="team-1", usage="agent.atlas.route", day="2026-09-01"):
    return {"id": f"id-{i}", "team_id": team, "usage_key": usage,
            "created_at": f"{day}T10:00:{i:02d}+00:00"}


@pytest.fixture
def fake_table(monkeypatch):
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    rows = [
        _row(1, day="2026-09-01"),  # old, route, team-1 → delete
        _row(2, day="2026-09-02"),  # old, route, team-1 → delete
        _row(3, day="2026-09-15"),  # within 30d, route, team-1 → keep
        _row(4, day="2026-10-01"),  # recent, route, team-1 (keep)
        _row(5, team="team-2", day="2026-08-01"),  # old, team-2 (keep — different team)
        _row(6, usage="text.decision", day="2026-08-01"),  # old, different usage (keep)
    ]
    table = FakeTable(rows, now)
    monkeypatch.setattr(ai_decisions_db, "get_supabase", lambda: type("C", (), {"table": lambda s, t: table})())
    return table, rows, now


def test_prune_deletes_old_rows_of_team_and_usage(fake_table):
    table, rows, _ = fake_table
    deleted = ai_decisions_db.prune_decisions("team-1", "agent.atlas.route", 30)
    assert deleted == 2
    kept = sorted(r["id"] for r in rows)
    assert kept == ["id-3", "id-4", "id-5", "id-6"]
    ops = table.last_delete.ops
    assert ("eq", "team_id", "team-1") in ops
    assert ("eq", "usage_key", "agent.atlas.route") in ops
    assert any(op[0] == "lt" and op[1] == "created_at" for op in ops)


def test_prune_refuses_empty_team_id(fake_table):
    assert ai_decisions_db.prune_decisions("", "agent.atlas.route", 30) == 0
    table, rows, _ = fake_table
    assert len(rows) == 6  # nothing deleted


def test_prune_refuses_empty_usage_key(fake_table):
    assert ai_decisions_db.prune_decisions("team-1", "", 30) == 0
    table, rows, _ = fake_table
    assert len(rows) == 6


def test_prune_returns_zero_on_error(monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(ai_decisions_db, "get_supabase", boom)
    assert ai_decisions_db.prune_decisions("team-1", "agent.atlas.route", 30) == 0


def test_prune_with_30_days_keeps_recent_rows(fake_table):
    table, rows, _ = fake_table
    deleted = ai_decisions_db.prune_decisions("team-1", "agent.atlas.route", 30)
    assert deleted == 2
    assert any(r["id"] == "id-3" for r in rows)  # 2026-09-15, within 30d of 2026-10-05
    assert any(r["id"] == "id-4" for r in rows)
"""BUG-0612: every required ai_budgets column must be written by upsert_bucket.

The finer-buckets migration (066) re-keyed ai_budgets but left the legacy team_id NOT NULL, so every
non-team budget save failed in the database while every unit test (fake Supabase) passed. This test
replays the ordered schema files: each NOT NULL column without a default that is still present at the
end must be in the row upsert_bucket sends.
"""

import re
from pathlib import Path

from shared.src.lib.database import ai_routing_db

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "setup" / "db" / "schema"


def _required_columns() -> set[str]:
    required: set[str] = set()
    for f in sorted(SCHEMA_DIR.glob("*.sql")):
        sql = re.sub(r"--[^\n]*", "", f.read_text())
        table = re.search(r"CREATE TABLE IF NOT EXISTS public\.ai_budgets \((.*?)\n\);", sql, re.S)
        if table:
            for line in table.group(1).splitlines():
                m = re.match(r"\s*(\w+)\s+[A-Z]", line)
                if m and ("NOT NULL" in line or "PRIMARY KEY" in line) and "DEFAULT" not in line:
                    required.add(m.group(1))
        for stmt in re.findall(r"ALTER TABLE public\.ai_budgets(.*?);", sql, re.S):
            for col in re.findall(r"DROP COLUMN IF EXISTS (\w+)", stmt):
                required.discard(col)
            for col in re.findall(r"ALTER COLUMN (\w+) SET NOT NULL", stmt):
                required.add(col)
            for col in re.findall(r"ALTER COLUMN (\w+) DROP NOT NULL", stmt):
                required.discard(col)
            for m in re.finditer(r"ADD COLUMN IF NOT EXISTS (\w+)([^,]*)", stmt):
                if "NOT NULL" in m.group(2) and "DEFAULT" not in m.group(2):
                    required.add(m.group(1))
    return required


class _FakeTable:
    def __init__(self, sink):
        self.sink = sink

    def upsert(self, row, on_conflict=None):
        self.sink.append(row)
        return self

    def execute(self):
        return type("R", (), {"data": [self.sink[-1]]})()


def test_upsert_bucket_writes_every_required_column(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(ai_routing_db, "get_supabase", lambda: type("S", (), {"table": lambda _s, _n: _FakeTable(sent)})())
    ai_routing_db.upsert_bucket("endpoint", "anthropic", "team-1", 80, "warn", 0.8, None, None)
    required = _required_columns()
    assert "team_scope" in required and "team_id" not in required
    missing = {c for c in required if sent[0].get(c) is None}
    assert not missing, f"ai_budgets requires {sorted(missing)} but upsert_bucket does not write them"

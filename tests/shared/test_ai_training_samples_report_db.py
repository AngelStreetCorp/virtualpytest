"""BUG-0495: list_for_report must select the id column that _parse_row reads (panel showed "'id'")."""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from shared.src.lib.database import ai_training_samples_db as db  # noqa: E402

ROW = {"id": "7", "family": "banner", "device_model": "stb-x", "label_source": "run", "is_failure": False,
       "label_conflict": False, "source_ref": '{"request_id": "r1"}'}


class FakeQuery:
    """Returns only the selected columns, like PostgREST, so a missing column shows up as a missing key."""

    def __init__(self, rows):
        self.rows, self.cols, self.window = rows, None, (0, 10**9)

    def select(self, cols, **_):
        self.cols = [c.strip() for c in cols.split(",")]
        return self

    def order(self, *_, **__):
        return self

    def eq(self, *_):
        return self

    def range(self, a, b):
        self.window = (a, b)
        return self

    def execute(self):
        a, b = self.window
        data = [{c: r[c] for c in self.cols} for r in self.rows[a:b + 1]]
        return type("R", (), {"data": data})()


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _):
        return FakeQuery(self.rows)


def test_list_for_report_returns_rows_with_id_and_parsed_source_ref(monkeypatch):
    monkeypatch.setattr(db, "get_supabase", lambda: FakeClient([dict(ROW), dict(ROW, id="8")]))
    rows = db.list_for_report("team-1")
    assert [r["id"] for r in rows] == ["7", "8"]
    assert rows[0]["source_ref"] == {"request_id": "r1"}

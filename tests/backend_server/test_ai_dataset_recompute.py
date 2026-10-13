"""ai-dataset feature: step 4j ``scripts/recompute_conflicts.py`` (TASK-27).

Recomputes ``label_conflict`` for every row of a team under the step 4j rules (a
low-information dHash never conflicts, ``focus`` never conflicts). Pure: the DB list and
the flag write are fakes.

Run: pytest tests/backend_server/test_ai_dataset_recompute.py -v
"""
import importlib.util
import io
import json
import os
import sys

import pytest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_TEST_DIR, "..", ".."))
sys.path.insert(0, _REPO_ROOT)

pytestmark = pytest.mark.unit

TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
INFO = "0f" * 32                     # 128 set bits
NEAR = format(int(INFO, 16) ^ 0b1, "064x")
LOW = "0" * 63 + "3"                 # 2 set bits: colour bars / black


@pytest.fixture(scope="module")
def rc():
    path = os.path.join(_REPO_ROOT, "features", "ai-dataset", "scripts", "recompute_conflicts.py")
    spec = importlib.util.spec_from_file_location("recompute_conflicts_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(sid, family, dhash, truth, flag, node=None, model="stb", focus=None, **kw):
    row = {"id": sid, "team_id": TEAM, "family": family, "device_model": model, "node_id": node,
           "focus_label": focus, "dhash": dhash, "ground_truth": truth, "label_conflict": flag,
           "label_source": "run", "split": "train", "eval_version": None, "is_failure": False}
    row.update(kw)
    return row


class FakeDB:
    def __init__(self, rows, page_limit=None):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.writes = []

    def list_samples(self, team_id, limit=50, offset=0, **kw):
        assert kw == {}, "the recompute must read every family / split / label source"
        mine = [r for r in self.rows.values() if r["team_id"] == team_id]
        return [dict(r) for r in mine[offset:offset + limit]], len(mine)

    def set_label_conflict(self, team_id, ids, value=True):
        self.writes.append((list(ids), value))
        n = 0
        for sid in ids:
            r = self.rows.get(sid)
            if r and r["team_id"] == team_id:
                r["label_conflict"] = value
                n += 1
        return n


def _world():
    return [
        # 4j cause 1: blank-ish screen-id rows with different labels, flagged under the old rules
        _row("bars", "screen-id", LOW, {"node_id": "poweroff"}, True, node="poweroff"),
        _row("black", "screen-id", "0" * 64, {"node_id": "live"}, True, node="live"),
        _row("tvshop", "screen-id", "0" * 64, {"node_id": "tvshop"}, True, node="tvshop",
             eval_version="eval-v1", split="eval"),                      # frozen row: flag only
        # 4j cause 2: focus highlights
        _row("f1", "focus", INFO, {"focused": "Movies"}, True, node="menu", focus="Movies"),
        _row("f2", "focus", NEAR, {"focused": "Series"}, True, node="menu", focus="Series"),
        # a real informative look-alike pair: stays flagged
        _row("home", "screen-id", INFO, {"node_id": "home"}, True, node="home"),
        _row("guide", "screen-id", NEAR, {"node_id": "guide"}, True, node="guide"),
        # another team's row is never read nor written
        _row("other", "screen-id", LOW, {"node_id": "x"}, True, team_id="other-team"),
    ]


def test_dry_run_prints_counts_and_writes_nothing(rc):
    db = FakeDB(_world())
    out = io.StringIO()
    assert rc.main(["--team", TEAM, "--dry-run", "--json"], list_fn=db.list_samples,
                   set_fn=db.set_label_conflict, out=out) == 0
    assert db.writes == []
    text = out.getvalue()
    assert "would set 0 flag(s), would clear 5 flag(s)" in text
    report = json.loads(text[text.index('{\n  "team_id"'):])
    assert report["clear"] == ["bars", "black", "f1", "f2", "tvshop"] and report["set"] == []
    assert report["families"]["screen-id"]["low_info"] == 3
    assert report["families"]["focus"]["flagged_after"] == 0
    assert report["families"]["screen-id"]["flagged_after"] == 2


def test_real_run_clears_low_info_and_focus_flags_only_and_is_idempotent(rc):
    db = FakeDB(_world())
    before = {k: dict(v) for k, v in db.rows.items()}
    assert rc.main(["--team", TEAM], list_fn=db.list_samples, set_fn=db.set_label_conflict,
                   out=io.StringIO()) == 0
    assert db.writes == [(["bars", "black", "f1", "f2", "tvshop"], False)]
    flags = {k: v["label_conflict"] for k, v in db.rows.items()}
    assert flags == {"bars": False, "black": False, "tvshop": False, "f1": False, "f2": False,
                     "home": True, "guide": True, "other": True}
    for sid, row in db.rows.items():   # nothing but the flag changed
        for key in ("ground_truth", "split", "label_source", "eval_version", "is_failure", "dhash"):
            assert row[key] == before[sid][key]
    out = io.StringIO()
    assert rc.main(["--team", TEAM], list_fn=db.list_samples, set_fn=db.set_label_conflict, out=out) == 0
    assert "set 0 flag(s), cleared 0 flag(s)" in out.getvalue()
    assert len(db.writes) == 1


def test_missing_flags_are_set(rc):
    rows = [_row("a", "screen-id", INFO, {"node_id": "home"}, False, node="home"),
            _row("b", "screen-id", NEAR, {"node_id": "guide"}, False, node="guide")]
    db = FakeDB(rows)
    assert rc.main(["--team", TEAM], list_fn=db.list_samples, set_fn=db.set_label_conflict,
                   out=io.StringIO()) == 0
    assert db.writes == [(["a", "b"], True)]


def test_pages_through_every_row(rc, monkeypatch):
    monkeypatch.setattr(rc, "PAGE_SIZE", 3)
    db = FakeDB(_world())
    rows = rc.fetch_all_rows(TEAM, list_fn=db.list_samples)
    assert sorted(r["id"] for r in rows) == sorted(k for k, v in db.rows.items() if v["team_id"] == TEAM)


def test_partial_read_is_refused_and_nothing_is_written(rc, capsys):
    db = FakeDB(_world())
    calls = []

    def flaky(team_id, limit=50, offset=0):
        calls.append(offset)
        if offset:
            return [], 0          # list_samples swallows DB errors as ([], 0)
        return db.list_samples(team_id, limit=2, offset=0)

    assert rc.main(["--team", TEAM], list_fn=flaky, set_fn=db.set_label_conflict) == 2
    assert db.writes == [] and "REFUSED" in capsys.readouterr().err


# ---- step 4k: screen-id conflicts compare screen groups --------------------------------------------

def test_home_tabs_are_not_a_conflict_once_compared_by_group(rc):
    from shared.src.lib.ai import screen_groups as sg
    key = {"command": "press_key", "params": {"key": "RIGHT"}}
    groups = sg.from_rows([{"node_id": n, "label": n} for n in ("home", "home_apps", "guide")],
                          [{"source_node_id": "home", "target_node_id": "home_apps", "default_action_set_id": "s",
                            "action_sets": [{"id": "s", "actions": [key]}]}])
    rows = [_row("h", "screen-id", INFO, {"node_id": "home", "label": "home"}, True, node="home",
                 userinterface="stb_tv"),
            _row("t", "screen-id", NEAR, {"node_id": "home_apps", "label": "home_apps"}, True, node="home_apps",
                 userinterface="stb_tv"),
            _row("g", "screen-id", NEAR, {"node_id": "guide", "label": "guide"}, False, node="guide",
                 userinterface="stb_tv")]
    db = FakeDB(rows)
    out = io.StringIO()
    assert rc.main(["--team", TEAM, "--dry-run", "--json"], list_fn=db.list_samples,
                   set_fn=db.set_label_conflict, groups_for=lambda team, ui: groups if ui == "stb_tv" else None,
                   out=out) == 0
    text = out.getvalue()
    report = json.loads(text[text.index('{\n  "team_id"'):])
    # home vs home_apps: same group, not a conflict; both still conflict with guide
    assert report["set"] == ["g"] and report["clear"] == []
    # stored labels are never rewritten here
    assert db.rows["t"]["ground_truth"] == {"node_id": "home_apps", "label": "home_apps"}
    # without groups (pre-4k behaviour) home vs home_apps would be a pair too
    view = rc.as_groups(TEAM, rows, None)
    assert view is rows

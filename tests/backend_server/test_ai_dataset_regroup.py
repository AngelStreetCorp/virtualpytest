"""ai-dataset feature: step 4k ``scripts/regroup_screen_labels.py`` (TASK-27).

Rewrites stored ``screen-id`` labels as screen groups (Home with any tab focused is
``home``), keeps ``label_source`` and the ``node_id`` column, recomputes ``is_failure``,
rewrites the triage teacher label/answer, refuses frozen rows, and is idempotent. Pure: the
DB list and the write are fakes; the groups come from core ``screen_groups`` on a small tree.

Run: pytest tests/backend_server/test_ai_dataset_regroup.py -v
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

from shared.src.lib.ai import screen_groups as sg  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
H = "0f" * 32                                     # informative, identical frames
OTHER = "f0" * 32


@pytest.fixture(scope="module")
def rg():
    path = os.path.join(_REPO_ROOT, "features", "ai-dataset", "scripts", "regroup_screen_labels.py")
    spec = importlib.util.spec_from_file_location("regroup_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _groups():
    key = lambda k: {"command": "press_key", "params": {"key": k}}  # noqa: E731
    nodes = [{"node_id": n, "label": n, "node_type": "screen"} for n in
             ("home", "home_apps", "home_settings", "apps", "settings")]
    nodes.append({"node_id": "entry-node", "label": "ENTRY", "node_type": "entry"})
    edges = [{"source_node_id": a, "target_node_id": b, "default_action_set_id": f"{a}-{b}",
              "action_sets": [{"id": f"{a}-{b}", "actions": [key(k)]}]}
             for a, b, k in (("entry-node", "home", "HOME"), ("home", "home_apps", "RIGHT"),
                             ("home_apps", "home_settings", "RIGHT"), ("home_apps", "apps", "OK"),
                             ("home_settings", "settings", "OK"))]
    return sg.from_rows(nodes, edges)


GROUPS = _groups()


def groups_for(team, ui):
    assert team == TEAM
    return GROUPS if ui == "stb-testop" else None


def _row(sid, node, label=None, source="run", dhash=H, **kw):
    row = {"id": sid, "team_id": TEAM, "family": "screen-id", "device_model": "stb",
           "userinterface": "stb-testop", "node_id": node, "focus_label": None, "dhash": dhash,
           "ground_truth": {"node_id": node, "label": label or node} if node else None,
           "label_source": source, "label_conflict": False, "is_failure": False, "model_answer": None,
           "split": "train", "eval_version": None}
    row.update(kw)
    return row


class FakeDB:
    def __init__(self, rows):
        self.rows = {r["id"]: json.loads(json.dumps(r)) for r in rows}
        self.writes = []

    def list_samples(self, team_id, family=None, limit=50, offset=0, **kw):
        assert family == "screen-id" and kw == {}
        mine = [dict(r) for r in self.rows.values() if r["team_id"] == team_id and r["family"] == family]
        return mine[offset:offset + limit], len(mine)

    def write(self, team_id, sid, fields, label_source):
        self.writes.append((sid, sorted(fields)))
        row = self.rows[sid]
        if row["eval_version"] or row["label_source"] != label_source:
            return False
        row.update(json.loads(json.dumps(fields)))
        return True


def _main(rg, db, *extra, column=True):
    out = io.StringIO()
    code = rg.main(["--team", TEAM, *extra], list_fn=db.list_samples, groups_for=groups_for,
                   write_fn=db.write, column_fn=lambda: column, out=out)
    return code, out.getvalue()


def _world():
    triage = {"status": "agreed", "teacher_label": {"node_id": "home_settings", "label": "home_settings"},
              "teacher_answer": {"label": "home_settings"}, "teacher_model": "claude-sonnet-5"}
    return [
        _row("a", "home_apps"),                                      # tab of home
        _row("b", "home_settings", triage=triage),                   # tab of home, triaged
        _row("c", "home"),                                           # the group itself
        _row("d", "apps", dhash=OTHER),                              # a single screen
        _row("e", None, label_source="none"),                        # unlabelled
        dict(_row("f", None, source="human", dhash="3c" * 32), ground_truth={"node_id": None, "label": "popup"}),
        _row("g", "gone", dhash="c3" * 32),                          # node no longer in the tree
        _row("h", "home_apps", userinterface="no_tree_app", dhash="5a" * 32),   # app with no tree
        _row("i", "home_settings", source="human",                   # human label, verifier failed
             node_id=None, is_failure=True,
             model_answer={"expected_node_id": "home", "expected_label": "home", "verified": False}),
    ]


def test_dry_run_writes_nothing_and_reports(rg):
    db = FakeDB(_world())
    code, text = _main(rg, db, "--dry-run", "--json")
    assert code == 0 and db.writes == []
    report = json.loads(text[text.index("{"):])
    c = report["per_app"]["stb-testop"]
    assert (c.get("change"), c.get("unchanged", 0), c["unlabelled"], c["offtree"], c["stale"]) == (5, 0, 1, 1, 1)
    assert report["per_app"]["no_tree_app"]["no_tree"] == 1
    assert report["changed"] == 5 and report["written"] == 0
    # Home and its tabs (a, b, c, i) were confusable pairs; as groups they agree
    assert report["conflicts"]["before"] == 4 and report["conflicts"]["after"] == 0
    assert "home (3) -> home_apps [apps], home_settings [settings]" in text
    assert "would change 5 row(s)" in text


def test_real_run_rewrites_labels_keeps_source_and_node_column(rg):
    db = FakeDB(_world())
    code, text = _main(rg, db)
    assert code == 0
    a = db.rows["a"]
    assert a["ground_truth"] == {"node_id": "home", "label": "home", "node": "home_apps",
                                 "node_label": "home_apps", "focus": "apps"}
    assert a["node_id"] == "home_apps" and a["label_source"] == "run"
    assert db.rows["c"]["ground_truth"]["focus"] is None
    assert db.rows["d"]["ground_truth"]["node"] == "apps"
    # untouched rows
    assert db.rows["f"]["ground_truth"] == {"node_id": None, "label": "popup"}
    assert db.rows["g"]["ground_truth"] == {"node_id": "gone", "label": "gone"}
    assert db.rows["h"]["ground_truth"] == {"node_id": "home_apps", "label": "home_apps"}
    # is_failure through the label path: the verifier failed on that frame, still a failure
    assert db.rows["i"]["label_source"] == "human" and db.rows["i"]["is_failure"] is True
    assert dict(db.writes)["i"] == ["ground_truth"] and db.rows["i"]["node_id"] is None
    # triage: teacher label and answer as groups
    t = db.rows["b"]["triage"]
    assert t["teacher_label"]["node_id"] == "home" and t["teacher_label"]["node"] == "home_settings"
    assert t["teacher_answer"] == {"label": "home"} and t["status"] == "agreed"
    assert "next: recompute_conflicts.py" in text


def test_second_run_changes_nothing(rg):
    db = FakeDB(_world())
    _main(rg, db)
    db.writes.clear()
    code, text = _main(rg, db, "--json")
    report = json.loads(text[text.index("{"):])
    assert code == 0 and report["changed"] == 0 and db.writes == []


def test_frozen_rows_are_refused_and_listed(rg):
    rows = [_row("a", "home_apps", eval_version="eval-v1", source="human"), _row("b", "home_settings")]
    db = FakeDB(rows)
    code, text = _main(rg, db, "--json")
    report = json.loads(text[text.index("{"):])
    assert [r["id"] for r in report["frozen_refused"]] == ["a"]
    assert "REFUSED frozen row a (eval-v1" in text
    assert [sid for sid, _f in db.writes] == ["b"]                 # the rest is written
    assert db.rows["a"]["ground_truth"] == {"node_id": "home_apps", "label": "home_apps"}


def test_is_failure_is_recomputed_through_the_label_path(rg):
    # a model answer that named the tab: wrong under per-node labels? It now names the group.
    row = _row("a", "home_apps", model_answer={"node_id": "home", "label": "home"}, is_failure=True)
    db = FakeDB([row])
    _main(rg, db)
    assert db.rows["a"]["is_failure"] is False


def test_without_the_triage_column_only_labels_are_written(rg):
    db = FakeDB(_world())
    _main(rg, db, column=False)
    assert all("triage" not in fields for _sid, fields in db.writes)


def test_a_concurrent_label_change_is_not_overwritten(rg):
    db = FakeDB([_row("a", "home_apps")])
    real_write = db.write

    def racing(team_id, sid, fields, label_source):
        db.rows[sid]["label_source"] = "human"     # a human answered in between
        return real_write(team_id, sid, fields, label_source)
    db.write = racing
    code, text = _main(rg, db)
    assert code == 1 and "failed 1" in text
    assert db.rows["a"]["ground_truth"] == {"node_id": "home_apps", "label": "home_apps"}


def test_regroup_answer_maps_a_node_name_to_its_group(rg):
    assert rg.regroup_answer({"label": "home_apps"}, GROUPS) == {"label": "home"}
    assert rg.regroup_answer({"label": "apps"}, GROUPS) == {"label": "apps"}
    assert rg.regroup_answer({"node_id": None, "label": "popup"}, GROUPS) == {"node_id": None, "label": "popup"}
    assert rg.regroup_answer({"label": "unknown"}, GROUPS) == {"label": "unknown"}


# ---- label schema: the group form, backwards compatibility, "nothing focused" ----------------------

import importlib  # noqa: E402

label_schema = importlib.import_module("features.ai-dataset.lib.label_schema")


def test_grouped_screen_id_label_is_valid_and_old_labels_stay_valid():
    grouped = GROUPS.label_for("home_apps")
    assert label_schema.validate_label("screen-id", grouped) is None
    assert label_schema.validate_label("screen-id", GROUPS.label_for("home")) is None      # focus null
    assert label_schema.validate_label("screen-id", {"node_id": "home_apps", "label": "home_apps"}) is None
    assert label_schema.validate_label("screen-id", {"node_id": None, "label": "popup"}) is None
    assert label_schema.validate_label("screen-id", dict(grouped, focus=""))                # empty text
    assert label_schema.validate_label("screen-id", dict(grouped, node=""))
    assert label_schema.validate_label("screen-id", {"node_id": None, "label": "popup", "focus": "x"})
    assert label_schema.validate_label("screen-id", dict(grouped, extra=1))
    assert label_schema.normalize_label("screen-id", dict(grouped, focus="  Apps ")) == dict(grouped, focus="Apps")


def test_focus_label_accepts_nothing_focused():
    assert label_schema.validate_label("focus", {"focused": None}) is None
    assert label_schema.validate_label("focus", {"focused": "Settings"}) is None
    assert label_schema.validate_label("focus", {"focused": ""})
    assert label_schema.validate_label("focus", {})                                        # key required
    assert label_schema.label_from_model_answer("focus", {"focused": None}) == {"focused": None}


# ---- the /screen-groups route -------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from flask import Flask, request
    routes = importlib.import_module("features.ai-dataset.backend_server.server_training_samples_routes")
    calls = []

    def fake_groups(team_id, ui):
        calls.append((team_id, ui))
        return GROUPS if ui == "stb-testop" else None
    monkeypatch.setattr(routes.screen_group_scope, "groups_for", fake_groups)
    app = Flask(__name__)

    @app.before_request
    def _principal():
        request.user_role = request.headers.get("X-Test-Role", "admin")

    app.register_blueprint(routes.server_training_samples_bp)
    c = app.test_client()
    c.calls = calls
    return c


def test_screen_groups_route_lists_the_groups_of_one_app(client):
    r = client.get(f"/server/training-samples/screen-groups?team_id={TEAM}&userinterface=stb-testop")
    body = r.get_json()
    assert r.status_code == 200 and body["found"] is True
    home = next(g for g in body["groups"] if g["label"] == "home")
    assert [m["label"] for m in home["members"]] == ["home", "home_apps", "home_settings"]
    assert home["members"][1]["focus"] == "apps"
    assert client.calls == [(TEAM, "stb-testop")]
    none = client.get(f"/server/training-samples/screen-groups?team_id={TEAM}&userinterface=nope").get_json()
    assert none["found"] is False and none["groups"] == []


def test_screen_groups_route_needs_team_app_and_admin(client):
    assert client.get("/server/training-samples/screen-groups?userinterface=stb-testop").status_code == 400
    assert client.get(f"/server/training-samples/screen-groups?team_id={TEAM}").status_code == 400
    r = client.get(f"/server/training-samples/screen-groups?team_id={TEAM}&userinterface=stb-testop",
                   headers={"X-Test-Role": "tester"})
    assert r.status_code == 403

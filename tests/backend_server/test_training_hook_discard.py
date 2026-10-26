"""TASK-27 step 3a: a human discard/confirm labels the recorded training samples.

Pure: runs the two blueprints in a bare Flask app. The discard DB updates, the
sample lookup, the alert lookup and attach_ground_truth are all replaced, so no
network, DB or storage is touched and no sample row is written for any team.

Run: pytest tests/backend_server/test_training_hook_discard.py -v
"""
import os
import sys

import pytest
from flask import Flask

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.routes import server_alerts_routes as alerts_routes  # noqa: E402
from backend_server.src.routes import server_script_results_routes as script_routes  # noqa: E402
from shared.src.lib.ai import training_samples  # noqa: E402
from shared.src.lib.database import ai_training_samples_db as samples_db  # noqa: E402

pytestmark = pytest.mark.unit

_REAL_ATTACH = training_samples.attach_ground_truth

TEAM = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def env(monkeypatch):
    state = {"enabled": True, "samples": [], "lookups": [], "attached": [], "alert_lookups": [],
             "update_ok": True}

    monkeypatch.setattr(alerts_routes, "check_supabase", lambda: None)
    monkeypatch.setattr(script_routes, "check_supabase", lambda: None)
    monkeypatch.setattr(alerts_routes, "update_alert_discard_status",
                        lambda *a, **k: state["update_ok"])
    monkeypatch.setattr(script_routes, "update_script_discard_status",
                        lambda *a, **k: state["update_ok"])
    monkeypatch.setattr(training_samples, "enabled", lambda: state["enabled"])

    def fake_lookup(team_id, key, value):
        state["lookups"].append((team_id, key, value))
        return state["samples"]

    def fake_alert(alert_id):
        state["alert_lookups"].append(alert_id)
        return {"id": alert_id, "incident_type": "blackscreen"}

    def fake_attach(sample_id, team_id, ground_truth, label_source):
        state["attached"].append((sample_id, team_id, ground_truth, label_source))
        return True

    monkeypatch.setattr(samples_db, "get_samples_by_source_ref", fake_lookup)
    monkeypatch.setattr(alerts_routes, "get_alert_by_id", fake_alert)
    monkeypatch.setattr(training_samples, "attach_ground_truth", fake_attach)

    app = Flask(__name__)
    app.register_blueprint(alerts_routes.server_alerts_bp)
    app.register_blueprint(script_routes.server_script_results_bp)
    state["client"] = app.test_client()
    return state


def _alert(env, body, team=TEAM):
    url = "/server/alerts/updateDiscardStatus/alert-1" + (f"?team_id={team}" if team else "")
    return env["client"].put(url, json=body)


def _script(env, body, team=TEAM):
    url = "/server/script-results/updateDiscardStatus/sr-1" + (f"?team_id={team}" if team else "")
    return env["client"].put(url, json=body)


# ---- alerts --------------------------------------------------------------------------

def test_alert_discard_labels_every_sample_as_no_incident(env):
    env["samples"] = [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]
    resp = _alert(env, {"discard": True, "check_type": "manual"})
    assert resp.status_code == 200 and resp.get_json() == {"status": "success"}
    assert env["lookups"] == [(TEAM, "alert_id", "alert-1")]
    assert env["attached"] == [(s, TEAM, {"incident_type": None}, "human") for s in ("s1", "s2", "s3")]
    assert env["alert_lookups"] == ["alert-1"]  # one lookup: its screen id teaches the screen memory (BUG-0746)


def test_a_person_s_discard_and_keep_through_the_route_teach_the_screen(env, monkeypatch):
    """BUG-0746: the route had stopped calling the screen-memory teacher on a Discard."""
    from shared.src.lib.database import screen_fingerprints_db as sdb
    taught = []
    monkeypatch.setattr(alerts_routes, "get_alert_by_id",
                        lambda i: {"id": i, "incident_type": "freeze", "metadata": {"screen_id": "scr-1"}})
    monkeypatch.setattr(sdb, "set_human_verdict", lambda s, e, a: taught.append((s, e, a)))
    _alert(env, {"discard": True, "check_type": "manual"})
    _alert(env, {"discard": False, "check_type": "manual"})
    _alert(env, {"discard": True, "check_type": "ai"})
    assert taught == [("scr-1", True, "alert-1"), ("scr-1", False, "alert-1")]


def test_alert_manual_confirm_labels_with_the_alert_type(env):
    env["samples"] = [{"id": "s1"}]
    resp = _alert(env, {"discard": False, "check_type": "manual"})
    assert resp.get_json() == {"status": "success"}
    assert env["alert_lookups"] == ["alert-1"]
    assert env["attached"] == [("s1", TEAM, {"incident_type": "blackscreen"}, "human")]


def test_alert_non_manual_keep_is_not_a_human_label(env):
    env["samples"] = [{"id": "s1"}]
    resp = _alert(env, {"discard": False, "check_type": "ai"})
    assert resp.get_json() == {"status": "success"}
    assert env["lookups"] == [] and env["attached"] == []


def test_alert_feature_off_no_team_or_failed_update_touches_nothing(env):
    env["samples"] = [{"id": "s1"}]
    env["enabled"] = False
    assert _alert(env, {"discard": True}).get_json() == {"status": "success"}
    env["enabled"] = True
    assert _alert(env, {"discard": True}, team=None).get_json() == {"status": "success"}
    env["update_ok"] = False
    assert _alert(env, {"discard": True}).status_code == 404
    assert env["lookups"] == [] and env["attached"] == []


def test_alert_hook_failure_keeps_the_response(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(samples_db, "get_samples_by_source_ref", boom)
    resp = _alert(env, {"discard": True})
    assert resp.status_code == 200 and resp.get_json() == {"status": "success"}

    env["samples"] = [{"id": "s1"}]
    monkeypatch.setattr(samples_db, "get_samples_by_source_ref", lambda *a: env["samples"])
    monkeypatch.setattr(training_samples, "attach_ground_truth", boom)
    resp = _alert(env, {"discard": True})
    assert resp.status_code == 200 and resp.get_json() == {"status": "success"}


# ---- script results ------------------------------------------------------------------

def test_script_discard_flips_each_recorded_verdict(env):
    env["samples"] = [
        {"id": "v1", "object_key": "t/other/m/2026-09/v1.jpg", "model_answer": {"verified": True}},
        {"id": "v2", "object_key": "t/other/m/2026-09/v2.jpg", "model_answer": {"verified": False}},
        {"id": "n1", "object_key": "t/other/m/2026-09/n1.jpg", "model_answer": {"content": "x"}},
        {"id": "g1", "object_key": None, "model_answer": {"verified": True}},
    ]
    resp = _script(env, {"discard": True})
    assert resp.status_code == 200 and resp.get_json() == {"status": "success"}
    assert env["lookups"] == [(TEAM, "script_result_id", "sr-1")]
    assert env["attached"] == [
        ("v1", TEAM, {"verified": False}, "human"),
        ("v2", TEAM, {"verified": True}, "human"),
    ]


def test_script_undiscard_feature_off_or_no_team_touches_nothing(env):
    env["samples"] = [{"id": "v1", "object_key": "k", "model_answer": {"verified": True}}]
    assert _script(env, {"discard": False}).get_json() == {"status": "success"}
    assert _script(env, {"discard": True}, team=None).get_json() == {"status": "success"}
    env["enabled"] = False
    assert _script(env, {"discard": True}).get_json() == {"status": "success"}
    assert env["lookups"] == [] and env["attached"] == []


def test_script_hook_failure_keeps_the_response(env, monkeypatch):
    env["samples"] = [{"id": "v1", "object_key": "k", "model_answer": {"verified": True}}]

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(training_samples, "attach_ground_truth", boom)
    resp = _script(env, {"discard": True})
    assert resp.status_code == 200 and resp.get_json() == {"status": "success"}


# ---- step 4g: one freeze strip per alert -----------------------------------------------

STRIP = {"incident_type": "freeze", "evidence": "strip", "duration_ms": 30174,
         "diffs": [0.13], "frames": [0.0, 15.0, 30.2]}


def test_discard_labels_the_single_freeze_strip_through_the_real_attach(env, monkeypatch):
    """One strip sample per alert: the discard labels it {incident_type: null}, and the real
    attach_ground_truth marks it a model failure."""
    row = {"id": "strip-1", "team_id": TEAM, "family": "av-fault", "device_model": "stb",
           "dhash": "0" * 64, "node_id": None, "focus_label": None, "model_answer": STRIP,
           "ground_truth": None, "source_ref": {"alert_id": "alert-1", "host": "h", "device": "d"}}
    updates = []
    monkeypatch.setattr(training_samples, "attach_ground_truth", _REAL_ATTACH)
    monkeypatch.setattr(samples_db, "get_sample", lambda sid, team: dict(row) if sid == "strip-1" else None)
    monkeypatch.setattr(samples_db, "get_group", lambda *a, **k: [])
    monkeypatch.setattr(samples_db, "update_label",
                        lambda *a: updates.append(a) or True)
    env["samples"] = [row]
    resp = _alert(env, {"discard": True, "check_type": "manual"})
    assert resp.get_json() == {"status": "success"}
    assert env["lookups"] == [(TEAM, "alert_id", "alert-1")]
    assert updates == [("strip-1", TEAM, {"incident_type": None}, "human", True, False)]

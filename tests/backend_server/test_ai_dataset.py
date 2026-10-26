"""ai-dataset feature (features/ai-dataset): training-sample review routes (list, label,
freeze; TASK-27 step 4), plus the feature's registration with DISABLED_FEATURES.

Pure: the blueprint runs in a bare Flask app whose before_request sets the caller's
role (as the global /server/* guard does), and every DB/storage call is replaced.
No network, DB or bucket is touched.

Run: pytest tests/backend_server/test_ai_dataset.py -v
"""
import importlib
import os
import sys
from urllib.parse import urlparse

import pytest
from flask import Flask, request

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

# The feature folder name has a hyphen, so it is imported by name (docs/technical/FEATURES.md).
routes = importlib.import_module("features.ai-dataset.backend_server.server_training_samples_routes")  # noqa: E402
from shared.src.lib.ai import training_samples  # noqa: E402
from shared.src.lib.database import ai_training_samples_db as samples_db  # noqa: E402
from shared.src.lib.utils import cloudflare_utils  # noqa: E402
from shared.src.lib.utils import features as feature_discovery  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = "11111111-1111-1111-1111-111111111111"
HASH = "0f" * 32   # informative (128 set bits): step 4j never compares a low-information hash


def _row(sid, family="banner", **kw):
    row = {"id": sid, "team_id": TEAM, "family": family, "object_key": f"{TEAM}/{family}/m/{sid}.jpg",
           "dhash": HASH, "device_model": "stb", "userinterface": "ui", "node_id": None,
           "focus_label": None, "model_answer": None, "ground_truth": None, "label_source": "none",
           "is_failure": False, "label_conflict": False, "split": "eval", "eval_version": None}
    row.update(kw)
    return row


class FakeBody:
    """The streaming body of a boto3 get_object answer."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self, amt=None):
        return self._data if amt is None else self._data[:amt]


class FakeS3Client:
    def __init__(self, body: bytes = b"\x00\xff\xd8\xff-jpeg", content_type: str = "image/jpeg",
                 error: Exception = None):
        self.body = body
        self.content_type = content_type
        self.error = error
        self.keys = []

    def get_object(self, Bucket=None, Key=None):  # noqa: N803 (boto3 spelling)
        self.keys.append((Bucket, Key))
        if self.error:
            raise self.error
        return {"Body": FakeBody(self.body), "ContentType": self.content_type}


class FakeStorage:
    def __init__(self, client=None):
        self.bucket_name = "vpt-training"
        self.s3_client = client or FakeS3Client()

    def set_client(self, client):
        self.s3_client = client

    def generate_presigned_url(self, key, expires_in=3600):
        return {"success": True, "url": f"https://signed.example/{key}?exp={expires_in}"}


@pytest.fixture
def env(monkeypatch):
    state = {"rows": {}, "list_calls": [], "updates": [], "update_ok": True, "freeze_after_check": False,
             "candidates": 0, "versions": set(), "frozen": [], "flagged": []}

    def fake_list(team_id, family=None, split=None, label_sources=None, is_failure=None,
                  device_model=None, limit=50, offset=0, label_conflict=None):
        state["list_calls"].append(dict(team_id=team_id, family=family, split=split,
                                        label_sources=label_sources, is_failure=is_failure,
                                        device_model=device_model, limit=limit, offset=offset,
                                        label_conflict=label_conflict))
        rows = [dict(r) for r in state["rows"].values() if r["team_id"] == team_id
                and (label_conflict is None or r["label_conflict"] is label_conflict)]
        return rows[offset:offset + limit], len(rows)

    def fake_labelled(team_id, family, device_model, limit=2000):
        return [(r["id"], r["dhash"], r["ground_truth"]) for r in state["rows"].values()
                if (r["team_id"], r["family"], r["device_model"]) == (team_id, family, device_model)
                and r["ground_truth"] is not None][:limit]

    def fake_set_conflict(team_id, ids, value=True):
        state["flagged"].append((team_id, list(ids)) if value else (team_id, list(ids), False))
        for i in ids:
            if i in state["rows"] and state["rows"][i]["team_id"] == team_id:
                state["rows"][i]["label_conflict"] = value
        return len(ids)

    def fake_get(sample_id, team_id):
        row = state["rows"].get(sample_id)
        if not row or row["team_id"] != team_id:
            return None
        return dict(row)

    def fake_update(sample_id, team_id, gt, source, is_failure, conflict):
        state["updates"].append((sample_id, team_id, gt, source, is_failure, conflict))
        if state["update_ok"] and not state["freeze_after_check"] and sample_id in state["rows"]:
            state["rows"][sample_id].update(ground_truth=gt, label_source=source,
                                            is_failure=is_failure, label_conflict=conflict)
        if state["freeze_after_check"]:
            state["rows"][sample_id]["eval_version"] = "eval-v1"
            return False
        return state["update_ok"]

    def fake_freeze(team_id, family, version):
        state["frozen"].append((team_id, family, version))
        return state["candidates"]

    monkeypatch.setattr(samples_db, "list_samples", fake_list)
    monkeypatch.setattr(samples_db, "get_sample", fake_get)
    monkeypatch.setattr(samples_db, "get_group", lambda *a, **k: [])
    monkeypatch.setattr(samples_db, "get_labelled_hashes", fake_labelled)
    monkeypatch.setattr(samples_db, "set_label_conflict", fake_set_conflict)
    monkeypatch.setattr(samples_db, "update_label", fake_update)
    monkeypatch.setattr(samples_db, "count_freeze_candidates", lambda t, f: state["candidates"])
    monkeypatch.setattr(samples_db, "eval_version_exists",
                        lambda t, f, v: (t, f, v) in state["versions"])
    monkeypatch.setattr(samples_db, "freeze_eval", fake_freeze)
    state["offtree"] = {TEAM: ["banner ad", "popup"]}
    state["offtree_calls"] = []

    def fake_offtree(team_id, family="screen-id", limit=2000):
        state["offtree_calls"].append((team_id, family))
        return list(state["offtree"].get(team_id, []))

    monkeypatch.setattr(samples_db, "get_offtree_labels", fake_offtree)
    storage = FakeStorage()
    monkeypatch.setattr(cloudflare_utils, "get_training_storage", lambda: storage)
    state["storage"] = storage
    # Review must not depend on the capture switch.
    monkeypatch.setattr(training_samples, "enabled", lambda: False)

    app = Flask(__name__)

    @app.before_request
    def _principal():
        request.user_role = request.headers.get("X-Test-Role", "admin")

    app.register_blueprint(routes.server_training_samples_bp)
    state["client"] = app.test_client()
    return state


def _list(env, qs="", role="admin"):
    return env["client"].get(f"/server/training-samples/list?team_id={TEAM}{qs}",
                             headers={"X-Test-Role": role})


def _label(env, sid, gt, role="admin", team=TEAM):
    return env["client"].post(f"/server/training-samples/{sid}/label",
                              json={"team_id": team, "ground_truth": gt, "label_source": "human"},
                              headers={"X-Test-Role": role})


def _freeze(env, family="banner", version="eval-v1", role="admin"):
    return env["client"].post("/server/training-samples/freeze",
                              json={"team_id": TEAM, "family": family, "version": version},
                              headers={"X-Test-Role": role})


# ---- access ------------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["viewer", "tester"])
def test_non_admin_is_refused_everywhere(env, role):
    env["rows"]["s1"] = _row("s1")
    assert _list(env, role=role).status_code == 403
    assert _label(env, "s1", {"channel_number": "1"}, role=role).status_code == 403
    assert _freeze(env, role=role).status_code == 403
    assert env["client"].get(f"/server/training-samples/eval-counts?team_id={TEAM}",
                             headers={"X-Test-Role": role}).status_code == 403
    assert env["client"].get(f"/server/training-samples/offtree-labels?team_id={TEAM}",
                             headers={"X-Test-Role": role}).status_code == 403
    assert env["updates"] == [] and env["frozen"] == [] and env["offtree_calls"] == []


def test_team_id_is_required(env):
    resp = env["client"].get("/server/training-samples/list")
    assert resp.status_code == 400


# ---- list --------------------------------------------------------------------------------

def test_list_passes_filters_and_team(env):
    resp = _list(env, "&family=banner&split=eval&label_source=none,run&is_failure=true"
                      "&device_model=stb&limit=20&offset=40")
    assert resp.status_code == 200
    assert env["list_calls"] == [dict(team_id=TEAM, family="banner", split="eval",
                                      label_sources=["none", "run"], is_failure=True,
                                      device_model="stb", limit=20, offset=40,
                                      label_conflict=None)]


def test_list_refuses_unknown_filter_values(env):
    assert _list(env, "&family=nope").status_code == 400
    assert _list(env, "&split=nope").status_code == 400
    assert _list(env, "&label_source=none,bogus").status_code == 400
    assert _list(env, "&balance=node_id").status_code == 400
    assert env["list_calls"] == []


def test_list_is_team_scoped(env):
    env["rows"]["mine"] = _row("mine")
    env["rows"]["theirs"] = _row("theirs", team_id="22222222-2222-2222-2222-222222222222")
    ids = [s["id"] for s in _list(env).get_json()["samples"]]
    assert ids == ["mine"]


def test_list_points_at_the_image_route_and_proposes_labels(env):
    env["rows"]["run"] = _row("run", ground_truth={"channel_number": "101"}, label_source="run",
                              model_answer={"channel_number": "102", "channel_name": "BBC"})
    env["rows"]["model"] = _row("model", model_answer={"channel_number": "5", "channel_name": "",
                                                       "program_name": "News", "confidence": 0.9})
    body = _list(env).get_json()
    by_id = {s["id"]: s for s in body["samples"]}
    # The screenshot is served by the app itself: the browser cannot read the
    # training bucket (BUG-0775).
    assert by_id["run"]["image_path"] == "/server/training-samples/run/image"
    # y on a run-label row keeps the run label, not the model answer
    assert by_id["run"]["proposed_label"] == {"channel_number": "101"}
    # otherwise the model answer mapped onto the family schema (empty fields dropped)
    assert by_id["model"]["proposed_label"] == {"channel_number": "5"}
    assert by_id["run"]["guess_source"] == "run"
    assert by_id["model"]["guess_source"] == "model"


def test_guess_source_is_none_without_a_guess(env):
    env["rows"]["s1"] = _row("s1", family="screen-id", model_answer={"content": "no idea"})
    sample = _list(env).get_json()["samples"][0]
    assert sample["proposed_label"] is None and sample["guess_source"] is None


# ---- the screenshot ---------------------------------------------------------------------

def _image(env, sid, team=TEAM, role="admin"):
    return env["client"].get(f"/server/training-samples/{sid}/image?team_id={team}",
                              headers={"X-Test-Role": role})


def test_image_route_serves_the_screenshot(env):
    """The server reads the object and hands the bytes over (BUG-0775)."""
    env["rows"]["s1"] = _row("s1")
    storage = env["storage"]

    resp = _image(env, "s1")
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert resp.data == storage.s3_client.body
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    # the object key comes from the database, never from the request
    assert storage.s3_client.keys == [("vpt-training", f"{TEAM}/banner/m/s1.jpg")]


@pytest.mark.parametrize("ctype", ["text/html", "application/octet-stream", "application/javascript"])
def test_image_route_refuses_a_non_image_content_type(env, ctype):
    env["rows"]["s1"] = _row("s1")
    env["storage"].set_client(FakeS3Client(body=b"<script>alert(1)</script>", content_type=ctype))
    resp = _image(env, "s1")
    assert resp.status_code == 415
    assert b"script" not in resp.data


def test_image_route_does_not_buffer_an_oversized_object(env, monkeypatch):
    env["rows"]["s1"] = _row("s1")
    monkeypatch.setattr(routes, "IMAGE_MAX_BYTES", 8)
    env["storage"].set_client(FakeS3Client(body=b"x" * 100))
    assert _image(env, "s1").status_code == 413


def test_image_route_refuses_another_team_and_unknown_samples(env):
    env["rows"]["mine"] = _row("mine")
    env["rows"]["theirs"] = _row("theirs", team_id="22222222-2222-2222-2222-222222222222")
    assert _image(env, "theirs").status_code == 404
    assert _image(env, "nope").status_code == 404


def test_image_route_says_when_a_sample_has_no_screenshot(env):
    env["rows"]["s1"] = _row("s1", object_key=None)
    resp = _image(env, "s1")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "This sample has no screenshot"


def test_image_route_reports_a_storage_failure(env):
    env["rows"]["s1"] = _row("s1")
    env["storage"].set_client(FakeS3Client(error=RuntimeError("minio is down")))
    resp = _image(env, "s1")
    assert resp.status_code == 502
    assert "could not be read" in resp.get_json()["error"]


def test_image_route_needs_the_team_and_a_permission(env):
    env["rows"]["s1"] = _row("s1")
    assert env["client"].get("/server/training-samples/s1/image").status_code == 400
    assert _image(env, "s1", role="viewer").status_code == 403


def test_model_that_saw_no_banner_proposes_no_banner(env):
    answer = {"channel_number": "", "channel_name": "", "program_name": "", "confidence": 0.1}
    assert routes.label_from_model_answer("banner", answer) == {"channel_number": None,
                                                                "channel_name": None}
    # an answer that is not banner-shaped at all is not "no banner"
    assert routes.label_from_model_answer("banner", {"content": "garbage"}) is None
    env["rows"]["s1"] = _row("s1", model_answer=answer)
    proposed = _list(env).get_json()["samples"][0]["proposed_label"]
    assert _label(env, "s1", proposed).status_code == 200
    assert env["updates"][0][2] == {"channel_number": None, "channel_name": None}
    assert env["updates"][0][4] is False  # the model was right: no banner


def test_eval_counts_per_family_team_scoped(env, monkeypatch):
    calls = []

    def fake_count(team_id, family):
        calls.append((team_id, family))
        return 200 if family == "banner" else 3

    monkeypatch.setattr(samples_db, "count_freeze_candidates", fake_count)
    body = env["client"].get(f"/server/training-samples/eval-counts?team_id={TEAM}").get_json()
    assert body["threshold"] == routes.FREEZE_MIN_ROWS
    assert body["counts"]["banner"] == 200 and body["counts"]["focus"] == 3
    assert set(body["counts"]) == set(routes.LABEL_SCHEMAS)
    assert {t for t, _ in calls} == {TEAM}
    assert env["client"].get("/server/training-samples/eval-counts").status_code == 400


def test_balance_round_robins_device_models(env):
    for i, model in enumerate(["a", "a", "a", "b", "b", "c"]):
        env["rows"][f"s{i}"] = _row(f"s{i}", device_model=model)
    body = _list(env, "&balance=device_model&limit=5").get_json()
    assert [s["device_model"] for s in body["samples"]] == ["a", "b", "c", "a", "b"]
    assert [s["id"] for s in body["samples"]] == ["s0", "s3", "s5", "s1", "s4"]
    assert env["list_calls"][0]["limit"] == routes.BALANCE_POOL
    page2 = _list(env, "&balance=device_model&limit=5&offset=5").get_json()
    assert [s["id"] for s in page2["samples"]] == ["s2"]


def test_round_robin_keeps_order_within_a_model():
    rows = [{"k": "x", "n": 1}, {"k": "y", "n": 2}, {"k": "x", "n": 3}, {"k": "x", "n": 4}]
    assert [r["n"] for r in routes.round_robin(rows, "k")] == [1, 2, 3, 4]


# ---- label schema ------------------------------------------------------------------------

@pytest.mark.parametrize("family,label", [
    ("screen-id", {"node_id": "n1", "label": "home"}),
    ("screen-id", {"node_id": None, "label": "popup"}),   # step 4f: screen not in the tree
    ("focus", {"focused": "Settings"}),
    ("banner", {"channel_number": "101", "channel_name": "BBC One"}),
    ("banner", {"channel_number": "101"}),
    ("banner", {"channel_number": None, "channel_name": None}),  # explicit "no banner"
    ("menu", {"items": ["English", "French"], "selected": "French"}),
    ("menu", {"items": ["English"], "selected": None}),
    ("av-fault", {"incident_type": "freeze"}),
    ("av-fault", {"incident_type": "blackscreen"}),
    ("av-fault", {"incident_type": "macroblocks"}),
    ("av-fault", {"incident_type": None}),
    ("content-type", {"screen": "live_tv", "category": "sport", "subcategory": "soccer"}),
    ("content-type", {"screen": "menu"}),
    ("content-type", {"screen": "vod_playback", "category": "movie", "subcategory": None}),
    ("other", {"verified": True}),
    ("other", ["anything"]),
])
def test_valid_labels(family, label):
    assert routes.validate_label(family, label) is None


@pytest.mark.parametrize("family,label", [
    ("screen-id", {"node_id": "n1"}),
    ("screen-id", {"node_id": "", "label": "home"}),
    ("screen-id", {"node_id": None, "label": ""}),
    ("screen-id", {"node_id": None, "label": "   "}),
    ("screen-id", {"node_id": None, "label": None}),
    ("screen-id", {"node_id": None}),
    ("screen-id", {"label": "popup"}),
    ("focus", {"focused": ""}),
    ("focus", {"focused": "x", "extra": 1}),
    ("banner", {"channel_number": "", "channel_name": None}),
    ("banner", "101"),
    ("banner", {}),
    ("banner", {"channel_number": None}),
    ("menu", {"items": []}),
    ("menu", {"items": ["English"], "selected": "German"}),
    ("av-fault", {"incident_type": "gremlins"}),
    ("av-fault", {"incident_type": "audio_loss"}),   # step 4f: not visible in a frame
    ("av-fault", {}),
    ("content-type", {"screen": "tv_show"}),
    ("content-type", {"screen": "menu", "category": "sport"}),            # category only on playback
    ("content-type", {"screen": "live_tv", "category": "cooking"}),
    ("content-type", {"screen": "live_tv", "subcategory": "soccer"}),     # kind without a category
    ("other", None),
    ("nope", {}),
])
def test_invalid_labels(family, label):
    assert routes.validate_label(family, label) is not None


def test_menu_answer_maps_from_language_analysis():
    answer = {"content": '```json\n{"menu_detected": true, "audio_languages": ["English", "French"],'
                         ' "subtitle_languages": ["Off"], "selected_audio": 1}\n```'}
    assert routes.label_from_model_answer("menu", answer) == {"items": ["English", "French"],
                                                              "selected": "French"}


def test_label_writes_human_label(env):
    env["rows"]["s1"] = _row("s1", model_answer={"channel_number": "5", "channel_name": "BBC"})
    resp = _label(env, "s1", {"channel_number": "6"})
    assert resp.status_code == 200, resp.get_json()
    assert env["updates"] == [("s1", TEAM, {"channel_number": "6"}, "human", True, False)]


def test_label_refuses_schema_violation(env):
    env["rows"]["s1"] = _row("s1", family="screen-id")
    resp = _label(env, "s1", {"node_id": "n1"})
    assert resp.status_code == 400 and "missing" in resp.get_json()["error"]
    assert env["updates"] == []


def test_label_refuses_non_human_source(env):
    env["rows"]["s1"] = _row("s1")
    resp = env["client"].post("/server/training-samples/s1/label",
                              json={"team_id": TEAM, "ground_truth": {"channel_number": "1"},
                                    "label_source": "teacher"})
    assert resp.status_code == 400 and env["updates"] == []


def test_accepting_a_run_label_keeps_the_run_ground_truth(env):
    env["rows"]["s1"] = _row("s1", ground_truth={"channel_number": "101"}, label_source="run",
                             model_answer={"channel_number": "101", "channel_name": "BBC"})
    proposed = _list(env).get_json()["samples"][0]["proposed_label"]
    resp = _label(env, "s1", proposed)
    assert resp.status_code == 200
    sid, team, gt, source, is_failure, _ = env["updates"][0]
    assert gt == {"channel_number": "101"} and source == "human" and is_failure is False


def test_label_other_team_sample_is_not_found(env):
    env["rows"]["s1"] = _row("s1", team_id="22222222-2222-2222-2222-222222222222")
    assert _label(env, "s1", {"channel_number": "1"}).status_code == 404
    assert env["updates"] == []


def test_label_works_with_capture_off(env):
    assert training_samples.enabled() is False
    env["rows"]["s1"] = _row("s1", family="focus", model_answer={"focused": "Home"})
    assert _label(env, "s1", {"focused": "Home"}).status_code == 200
    assert env["updates"][0][4] is False  # model was right


def test_frozen_row_gives_409(env):
    env["rows"]["s1"] = _row("s1", eval_version="eval-v1")
    resp = _label(env, "s1", {"channel_number": "1"})
    assert resp.status_code == 409 and "frozen" in resp.get_json()["error"]
    assert env["updates"] == []


def test_freeze_trigger_refusal_gives_409(env):
    env["rows"]["s1"] = _row("s1")
    env["freeze_after_check"] = True  # trigger raised: row frozen between check and update
    assert _label(env, "s1", {"channel_number": "1"}).status_code == 409


def test_other_update_failure_gives_500(env):
    env["rows"]["s1"] = _row("s1")
    env["update_ok"] = False
    assert _label(env, "s1", {"channel_number": "1"}).status_code == 500


# ---- freeze ------------------------------------------------------------------------------

def test_freeze_refused_below_threshold(env):
    env["candidates"] = routes.FREEZE_MIN_ROWS - 1
    resp = _freeze(env)
    assert resp.status_code == 400 and resp.get_json()["candidates"] == 199
    assert env["frozen"] == []


def test_freeze_at_threshold_succeeds(env):
    env["candidates"] = routes.FREEZE_MIN_ROWS
    resp = _freeze(env)
    assert resp.status_code == 200 and resp.get_json()["frozen"] == 200
    assert env["frozen"] == [(TEAM, "banner", "eval-v1")]


def test_freeze_existing_version_gives_409(env):
    env["candidates"] = 500
    env["versions"].add((TEAM, "banner", "eval-v1"))
    assert _freeze(env).status_code == 409
    assert env["frozen"] == []


def test_freeze_validates_input(env):
    env["candidates"] = 500
    assert _freeze(env, family="nope").status_code == 400
    assert _freeze(env, version="v1; drop").status_code == 400
    assert env["frozen"] == []


# ---- storage presign ---------------------------------------------------------------------

@pytest.fixture
def fresh_training_storage(monkeypatch):
    monkeypatch.setattr(cloudflare_utils.TrainingStorage, "_instance", None)
    monkeypatch.setattr(cloudflare_utils.TrainingStorage, "_initialized", False)
    for key, value in {"MINIO_TRAINING_ENDPOINT": "http://192.168.0.101:9100",
                       "MINIO_TRAINING_ACCESS_KEY": "ak", "MINIO_TRAINING_SECRET_KEY": "sk",
                       "MINIO_TRAINING_BUCKET": "vpt-training"}.items():
        monkeypatch.setenv(key, value)
    yield
    cloudflare_utils.TrainingStorage._instance = None


def test_presign_endpoint_is_used_when_set(monkeypatch, fresh_training_storage):
    monkeypatch.setenv("MINIO_TRAINING_PRESIGN_ENDPOINT", "https://vpt-training.example.com")
    storage = cloudflare_utils.TrainingStorage()
    url = storage.generate_presigned_url("t/banner/m/x.jpg", expires_in=3600)["url"]
    assert urlparse(url).netloc == "vpt-training.example.com"
    assert "/vpt-training/t/banner/m/x.jpg" in url
    # uploads still go to the internal endpoint
    assert storage.s3_client.meta.endpoint_url == "http://192.168.0.101:9100"


def test_presign_falls_back_to_upload_client(monkeypatch, fresh_training_storage):
    monkeypatch.delenv("MINIO_TRAINING_PRESIGN_ENDPOINT", raising=False)
    storage = cloudflare_utils.TrainingStorage()
    assert storage.presign_client is None
    url = storage.generate_presigned_url("t/x.jpg")["url"]
    assert urlparse(url).netloc == "192.168.0.101:9100"


@pytest.mark.parametrize("qs,expected", [
    ("&label_source=none,run,teacher", ["none", "run", "teacher"]),  # Show: Not checked yet
    ("&label_source=human", ["human"]),                              # Show: Already checked
    ("", None),                                                      # Show: All
])
def test_show_views_map_to_label_source_filter(env, qs, expected):
    assert _list(env, qs).status_code == 200
    assert env["list_calls"][0]["label_sources"] == expected


# ---- step 4d: confusable pairs and failed verifications -----------------------------------

HOME = {"node_id": "n-home", "label": "Home"}
GUIDE = {"node_id": "n-guide", "label": "TV Guide"}
FAILED_ANSWER = {"expected_node_id": "n-home", "expected_label": "Home", "verified": False}


def test_confusable_pairs_filter(env):
    env["rows"]["a"] = _row("a", family="screen-id", ground_truth=HOME, label_conflict=True)
    env["rows"]["b"] = _row("b", family="screen-id", ground_truth=GUIDE, label_conflict=True)
    env["rows"]["c"] = _row("c", family="screen-id", ground_truth=HOME, dhash="f" * 64)
    resp = _list(env, "&label_conflict=true")
    assert resp.status_code == 200
    assert env["list_calls"][0]["label_conflict"] is True
    samples = {s["id"]: s for s in resp.get_json()["samples"]}
    assert set(samples) == {"a", "b"}
    # Details: each side names the other sample of the pair and its label.
    assert samples["a"]["conflict_partner"] == {"id": "b", "ground_truth": GUIDE}
    assert samples["b"]["conflict_partner"] == {"id": "a", "ground_truth": HOME}
    assert _list(env).get_json()["samples"][2]["conflict_partner"] is None


def test_label_on_failed_verification_sample_is_a_failure(env):
    env["rows"]["fv"] = _row("fv", family="screen-id", model_answer=FAILED_ANSWER)
    listed = _list(env).get_json()["samples"][0]
    assert listed["proposed_label"] is None and listed["guess_source"] is None   # no guess, no Yes
    resp = _label(env, "fv", HOME)      # even the expected screen: the check still failed here
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["is_failure"] is True
    assert env["updates"] == [("fv", TEAM, HOME, "human", True, False)]


def test_label_flags_both_sides_of_a_cross_node_conflict(env):
    env["rows"]["home"] = _row("home", family="screen-id", node_id="n-home", ground_truth=HOME,
                               label_source="run")
    env["rows"]["fv"] = _row("fv", family="screen-id", model_answer=FAILED_ANSWER)
    resp = _label(env, "fv", GUIDE)
    assert resp.status_code == 200
    assert resp.get_json()["label_conflict"] is True
    assert env["flagged"] == [(TEAM, ["home"])]


def test_label_same_screen_is_no_conflict(env):
    env["rows"]["home"] = _row("home", family="screen-id", node_id="n-home", ground_truth=HOME,
                               label_source="run")
    env["rows"]["fv"] = _row("fv", family="screen-id", model_answer=FAILED_ANSWER)
    resp = _label(env, "fv", HOME)
    assert resp.get_json()["label_conflict"] is False
    assert env["flagged"] == []


def test_label_that_resolves_a_pair_clears_the_partner_flag(env):
    env["rows"]["home"] = _row("home", family="screen-id", node_id="n-home", ground_truth=HOME,
                               label_source="run", label_conflict=True)
    env["rows"]["fv"] = _row("fv", family="screen-id", model_answer=FAILED_ANSWER,
                             ground_truth=GUIDE, label_source="human", label_conflict=True)
    resp = _label(env, "fv", HOME)
    assert resp.status_code == 200
    assert resp.get_json()["label_conflict"] is False
    assert env["rows"]["home"]["label_conflict"] is False
    assert env["flagged"] == [(TEAM, ["home"], False)]


# ---- feature registration (docs/technical/FEATURES.md) ------------------------------

def _other_features():
    return [f["name"] for f in feature_discovery.enabled_features() if f["name"] != "ai-dataset"]


def _registered_app(monkeypatch, disabled):
    """A bare Flask app with a core-like /server/<path> catch-all (app.py's auto_proxy is
    registered before the features), then the features' register(app) as app.py runs it."""
    monkeypatch.setenv("DISABLED_FEATURES", ",".join(disabled))
    app = Flask(__name__)
    app.add_url_rule("/server/<path:endpoint>", "auto_proxy", lambda endpoint: "proxied")
    feature_discovery.register_feature_blueprints(app, "backend_server")
    return app


def _endpoint(app, path, method="GET"):
    return app.url_map.bind("localhost").match(path, method=method)[0]


def test_feature_enabled_registers_the_review_routes(monkeypatch):
    # Every other feature off, so this checks ai-dataset alone in a bare env.
    app = _registered_app(monkeypatch, _other_features())
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/server/training-samples/list" in rules
    assert "/server/training-samples/<sample_id>/label" in rules
    assert "/server/training-samples/freeze" in rules
    assert "/server/training-samples/eval-counts" in rules
    assert "/server/training-samples/offtree-labels" in rules
    assert _endpoint(app, "/server/training-samples/offtree-labels") ==         "server_training_samples.training_offtree_labels"
    # Registered after the catch-all, the static paths still win over it.
    assert _endpoint(app, "/server/training-samples/list") == "server_training_samples.list_training_samples"
    assert _endpoint(app, "/server/training-samples/abc/label", "POST") ==         "server_training_samples.label_training_sample"


def test_feature_disabled_registers_nothing(monkeypatch):
    app = _registered_app(monkeypatch, _other_features() + ["ai-dataset"])
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert not any(r.startswith("/server/training-samples") for r in rules)
    # The path falls through to the core catch-all, like any absent feature.
    assert _endpoint(app, "/server/training-samples/list") == "auto_proxy"


# ---- step 4f: screen not in the tree, no audio in av-fault ------------------------------

POPUP = {"node_id": None, "label": "popup"}


def test_off_tree_label_is_saved_trimmed_lowercase_and_is_a_failure(env):
    env["rows"]["s1"] = _row("s1", family="screen-id", node_id="n-home",
                             model_answer={"node_id": "n-home", "label": "Home"})
    resp = _label(env, "s1", {"node_id": None, "label": "  Error / No Signal "})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ground_truth"] == {"node_id": None, "label": "error / no signal"}
    assert body["is_failure"] is True
    assert env["updates"] == [("s1", TEAM, {"node_id": None, "label": "error / no signal"},
                               "human", True, False)]


def test_off_tree_label_on_failed_verification_sample_is_a_failure(env):
    env["rows"]["fv"] = _row("fv", family="screen-id", model_answer=FAILED_ANSWER)
    resp = _label(env, "fv", POPUP)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["is_failure"] is True


def test_off_tree_labels_conflict_by_label(env):
    env["rows"]["a"] = _row("a", family="screen-id", ground_truth={"node_id": None, "label": "popup"},
                            label_source="human")
    env["rows"]["fv"] = _row("fv", family="screen-id", model_answer=FAILED_ANSWER)
    # same off-tree text (any case): no conflict
    resp = _label(env, "fv", {"node_id": None, "label": "POPUP"})
    assert resp.get_json()["label_conflict"] is False and env["flagged"] == []
    # another off-tree text on a near-identical frame: both sides flagged
    resp = _label(env, "fv", {"node_id": None, "label": "dialog"})
    assert resp.get_json()["label_conflict"] is True
    assert env["flagged"] == [(TEAM, ["a"])]


def test_off_tree_vs_tree_node_is_a_conflict(env):
    env["rows"]["home"] = _row("home", family="screen-id", node_id="n-home", ground_truth=HOME,
                               label_source="run")
    env["rows"]["fv"] = _row("fv", family="screen-id", model_answer=FAILED_ANSWER)
    resp = _label(env, "fv", POPUP)
    assert resp.get_json()["label_conflict"] is True
    assert env["flagged"] == [(TEAM, ["home"])]


def test_screen_id_with_a_node_still_needs_both_fields(env):
    env["rows"]["s1"] = _row("s1", family="screen-id")
    assert _label(env, "s1", {"node_id": "n1", "label": ""}).status_code == 400
    assert _label(env, "s1", {"node_id": None, "label": ""}).status_code == 400
    assert env["updates"] == []


def test_av_fault_refuses_audio_loss(env):
    env["rows"]["a1"] = _row("a1", family="av-fault", model_answer={"incident_type": "freeze"})
    resp = _label(env, "a1", {"incident_type": "audio_loss"})
    assert resp.status_code == 400 and "incident_type" in resp.get_json()["error"]
    assert env["updates"] == []
    assert "audio_loss" not in routes.AV_FAULT_TYPES


def test_offtree_labels_route_merges_starters_and_saved(env):
    resp = env["client"].get(f"/server/training-samples/offtree-labels?team_id={TEAM}")
    assert resp.status_code == 200, resp.get_json()
    labels = resp.get_json()["labels"]
    assert labels[:5] == ["popup", "error / no signal", "loading / black", "dialog", "tip"]
    assert labels[5:] == ["banner ad"]          # saved, not a starter: no duplicate "popup"
    assert env["offtree_calls"] == [(TEAM, "screen-id")]


def test_offtree_labels_route_is_team_scoped_and_screen_id_only(env):
    other = "22222222-2222-2222-2222-222222222222"
    resp = env["client"].get(f"/server/training-samples/offtree-labels?team_id={other}")
    assert resp.get_json()["labels"] == list(routes.OFFTREE_STARTER_LABELS)
    assert env["offtree_calls"] == [(other, "screen-id")]
    assert env["client"].get("/server/training-samples/offtree-labels").status_code == 400
    assert env["client"].get(f"/server/training-samples/offtree-labels?team_id={TEAM}&family=focus"
                             ).status_code == 400


# ---- step 4g: freeze strip answers ----------------------------------------------------

STRIP_ANSWER = {"incident_type": "freeze", "evidence": "strip", "duration_ms": 30174,
                "diffs": [0.13, 0.14, 0.11], "frames": [0.0, 15.0, 30.2]}


@pytest.mark.parametrize("answer,failure", [
    ({"incident_type": "freeze"}, False),                                  # Frozen, real problem
    ({"incident_type": None, "static_screen": True}, True),                # Still screen, not a problem
    ({"incident_type": None, "static_screen": False}, True),               # Moving, false alarm
])
def test_freeze_strip_answers_are_accepted_with_the_right_is_failure(env, answer, failure):
    env["rows"]["st"] = _row("st", family="av-fault", model_answer=STRIP_ANSWER,
                             source_ref={"alert_id": "alert-1"})
    resp = _label(env, "st", answer)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["ground_truth"] == answer and body["label_source"] == "human"
    assert body["is_failure"] is failure
    assert env["updates"] == [("st", TEAM, answer, "human", failure, False)]


def test_strip_proposed_label_is_the_incident_type_only(env):
    env["rows"]["st"] = _row("st", family="av-fault", model_answer=STRIP_ANSWER)
    sample = _list(env).get_json()["samples"][0]
    assert sample["proposed_label"] == {"incident_type": "freeze"}
    assert sample["model_answer"]["evidence"] == "strip"


@pytest.mark.parametrize("bad", [
    {"incident_type": None, "static_screen": "yes"},       # not a boolean
    {"incident_type": "freeze", "static_screen": True},    # only with a null type
    {"incident_type": None, "static_screen": None},
])
def test_static_screen_is_validated(env, bad):
    env["rows"]["st"] = _row("st", family="av-fault", model_answer=STRIP_ANSWER)
    resp = _label(env, "st", bad)
    assert resp.status_code == 400 and "static_screen" in resp.get_json()["error"]
    assert env["updates"] == []


def test_static_screen_is_never_compared_with_the_model_answer():
    """_differs compares only the label's keys, minus annotation keys: a model answer that
    happened to carry static_screen would not change is_failure."""
    answer = {"incident_type": None, "static_screen": False}
    assert training_samples._differs(answer, {"incident_type": None, "static_screen": True}) is False
    assert training_samples._differs({"incident_type": "freeze"},
                                     {"incident_type": None, "static_screen": True}) is True
    assert training_samples._differs({"incident_type": "freeze"}, {"incident_type": "freeze"}) is False


def test_discard_and_still_screen_labels_do_not_conflict(env, monkeypatch):
    """A discarded strip ({incident_type: null}) and a near-identical strip reviewed as a
    still screen agree: av-fault labels compare incident_type only. A near-identical
    strip confirmed as a freeze does conflict."""
    group = [("d1", HASH, {"incident_type": None}, False)]
    monkeypatch.setattr(samples_db, "get_group", lambda *a, **k: group)
    env["rows"]["st"] = _row("st", family="av-fault", model_answer=STRIP_ANSWER)
    resp = _label(env, "st", {"incident_type": None, "static_screen": True})
    assert resp.get_json()["label_conflict"] is False
    resp = _label(env, "st", {"incident_type": "freeze"})
    assert resp.get_json()["label_conflict"] is True

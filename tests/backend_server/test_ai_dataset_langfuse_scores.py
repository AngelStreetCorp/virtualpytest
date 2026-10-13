"""ai-dataset feature: verdicts and eval runs to Langfuse (TASK-27, 2026-10-04).

``lib/langfuse_scores.py`` with a fake Langfuse v2 client: the score name / value / trace,
the skips (no trace id, tracing off, no comparator), a client exception swallowed, the
label route's ``verdict_human`` and ``score_eval``'s dataset items, run links and scores.

Pure: no network, no DB, no Langfuse.

Run: pytest tests/backend_server/test_ai_dataset_langfuse_scores.py -v
"""
import importlib
import importlib.util
import os
import sys
import types

import pytest
from flask import Flask, request

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_TEST_DIR, "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from shared.src.lib.ai import training_samples, tracing  # noqa: E402
from shared.src.lib.database import ai_training_samples_db as samples_db  # noqa: E402

lf = importlib.import_module("features.ai-dataset.lib.langfuse_scores")  # noqa: E402
routes = importlib.import_module("features.ai-dataset.backend_server.server_training_samples_routes")  # noqa: E402
triage_db = importlib.import_module("features.ai-dataset.lib.triage_db")  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
TRACE = "57e38eab4a0141b29c931877e680d55f"
RUNTIME_BANNER = {"channel_name": "TELE ZURI HD", "channel_number": "", "program_name": "MediaShop",
                  "start_time": "08:00", "end_time": "09:00", "confidence": 0.9}


class FakeLangfuse:
    """The v2 SDK surface the module uses: score, create_dataset, create_dataset_item,
    client.dataset_run_items.create, flush."""

    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.scores, self.datasets, self.items, self.run_items = [], [], [], []
        self.flushed = 0
        self.client = types.SimpleNamespace(dataset_run_items=types.SimpleNamespace(create=self._run_item))

    def _maybe_fail(self, what):
        if what in self.fail_on:
            raise RuntimeError(f"langfuse down ({what})")

    def score(self, **kw):
        self._maybe_fail("score")
        self.scores.append(kw)

    def create_dataset(self, **kw):
        self._maybe_fail("dataset")
        self.datasets.append(kw)

    def create_dataset_item(self, **kw):
        self._maybe_fail("item")
        self.items.append(kw)

    def _run_item(self, request):
        self._maybe_fail("link")
        self.run_items.append(request)

    def flush(self):
        self.flushed += 1


def _banner_row(**kw):
    row = {"id": "s1", "team_id": TEAM, "family": "banner", "model_answer": dict(RUNTIME_BANNER),
           "ground_truth": None, "label_source": "none", "eval_version": None, "triage": None,
           "source_ref": {"zap_id": "z1", "trace_id": TRACE}, "dhash": "0f" * 32, "device_model": "stb",
           "node_id": None, "focus_label": None, "is_failure": False, "label_conflict": False}
    row.update(kw)
    return row


# ---- the score -------------------------------------------------------------------------------

def test_verdict_posts_a_boolean_score_on_the_rows_trace():
    client = FakeLangfuse()
    sid = lf.score_verdict(_banner_row(), {"channel_name": "Tele Zuri"}, lf.SCORE_HUMAN, "human: x", client=client)
    assert sid == lf.score_id(TRACE, "verdict_human")
    (score,) = client.scores
    assert (score["trace_id"], score["name"], score["value"], score["data_type"]) == (TRACE, "verdict_human", 1.0, "BOOLEAN")
    assert score["id"] == sid and score["comment"].startswith("human: x | match")
    lf.score_verdict(_banner_row(), {"channel_name": "SRF info"}, lf.SCORE_HUMAN, client=client)
    assert client.scores[1]["value"] == 0.0 and "name expected srfinfo" in client.scores[1]["comment"]
    assert client.scores[1]["id"] == sid  # same trace + name: the newer verdict replaces the older one


def test_unmappable_model_answer_scores_wrong_and_content_type_has_a_comparator():
    client = FakeLangfuse()
    lf.score_verdict(_banner_row(model_answer={}), {"channel_name": "BBC Two"}, lf.SCORE_AI, client=client)
    assert client.scores[0]["value"] == 0.0 and "unparsed" in client.scores[0]["comment"]
    ct = _banner_row(family="content-type", model_answer={"content": '{"screen": "live_tv", "category": "sport", '
                                                                     '"subcategory": "soccer", "entity": null}'})
    lf.score_verdict(ct, {"screen": "live_tv", "category": "sport", "subcategory": "football"}, lf.SCORE_HUMAN,
                     client=client)
    assert client.scores[1]["value"] == 1.0  # subcategory is free text, not compared
    lf.score_verdict(ct, {"screen": "advertisement"}, lf.SCORE_HUMAN, client=client)
    assert client.scores[2]["value"] == 0.0


def test_skipped_without_trace_id_or_comparator_or_client(monkeypatch):
    client = FakeLangfuse()
    assert lf.score_verdict(_banner_row(source_ref={"zap_id": "z"}), {"channel_name": "x"}, "n", client=client) is None
    assert lf.score_verdict(_banner_row(source_ref=None), {"channel_name": "x"}, "n", client=client) is None
    assert lf.score_verdict(_banner_row(family="other"), {"a": 1}, "n", client=client) is None
    assert client.scores == []
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)  # tracing off: no client, no thread
    assert lf.get_client() is None
    assert lf.score_verdict(_banner_row(), {"channel_name": "x"}, "n") is None
    assert lf.score_verdict_async(_banner_row(), {"channel_name": "x"}, "n") is None
    assert lf.trace_id_of({"source_ref": '{"trace_id": "abc"}'}) == "abc"


def test_a_client_exception_is_swallowed():
    client = FakeLangfuse(fail_on={"score"})
    assert lf.score_verdict(_banner_row(), {"channel_name": "x"}, "n", client=client) is None
    broken = types.SimpleNamespace(score=None)  # not even callable
    assert lf.post_score(broken, TRACE, "n", True) is None


def test_async_verdict_runs_in_a_daemon_thread():
    client = FakeLangfuse()
    thread = lf.score_verdict_async(_banner_row(), {"channel_name": "TELE ZURI"}, lf.SCORE_HUMAN, "c", client=client)
    assert thread is not None and thread.daemon
    thread.join(5)
    assert client.scores[0]["name"] == "verdict_human" and client.scores[0]["value"] == 1.0
    assert lf.score_verdict_async(_banner_row(source_ref=None), {}, "n", client=client) is None


# ---- the review label route ------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch):
    state = {"rows": {}, "async": []}
    monkeypatch.setattr(samples_db, "get_sample", lambda sid, t: dict(state["rows"][sid]) if sid in state["rows"] else None)
    monkeypatch.setattr(samples_db, "get_group", lambda *a, **k: [])
    monkeypatch.setattr(samples_db, "get_labelled_hashes", lambda *a, **k: [])
    monkeypatch.setattr(samples_db, "set_label_conflict", lambda *a, **k: 0)
    monkeypatch.setattr(samples_db, "update_label", lambda *a, **k: True)
    monkeypatch.setattr(triage_db, "resolve_triage", lambda *a: True)
    monkeypatch.setattr(training_samples, "enabled", lambda: False)
    client = FakeLangfuse()
    state["lf"] = client
    real_async = lf.score_verdict_async

    def spy(row, truth, name, comment=None, client=None):
        thread = real_async(row, truth, name, comment, client=state["lf"])
        state["async"].append((row["id"], name, thread))
        if thread:
            thread.join(5)
        return thread
    monkeypatch.setattr(routes.langfuse_scores, "score_verdict_async", spy)
    app = Flask(__name__)

    @app.before_request
    def _principal():
        request.user_role = "admin"

    app.register_blueprint(routes.server_training_samples_bp)
    state["client"] = app.test_client()
    return state


def test_human_label_posts_verdict_human_on_the_trace(api):
    api["rows"]["s1"] = _banner_row()
    resp = api["client"].post("/server/training-samples/s1/label",
                              json={"team_id": TEAM, "ground_truth": {"channel_name": "TELE ZURI HD"}})
    assert resp.status_code == 200
    (score,) = api["lf"].scores
    assert (score["trace_id"], score["name"], score["value"]) == (TRACE, "verdict_human", 1.0)
    assert score["comment"].startswith('human: {"channel_name": "TELE ZURI HD"}')


def test_human_label_without_trace_posts_nothing_and_a_langfuse_failure_never_fails_the_label(api):
    api["rows"]["n"] = _banner_row(id="n", source_ref={"zap_id": "z"})
    assert api["client"].post("/server/training-samples/n/label",
                              json={"team_id": TEAM, "ground_truth": {"channel_name": "x"}}).status_code == 200
    assert api["lf"].scores == [] and api["async"][0][2] is None
    api["lf"].fail_on.add("score")
    api["rows"]["s1"] = _banner_row()
    resp = api["client"].post("/server/training-samples/s1/label",
                              json={"team_id": TEAM, "ground_truth": {"channel_name": "x"}})
    assert resp.status_code == 200 and resp.get_json()["success"] is True


# ---- score_eval -> dataset run -------------------------------------------------------------------

@pytest.fixture(scope="module")
def score_eval():
    spec = importlib.util.spec_from_file_location(
        "score_eval_lf", os.path.join(_REPO_ROOT, "features", "ai-dataset", "scripts", "score_eval.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GROUPED = {"node_id": "n-home", "label": "home", "node": "n-apps", "node_label": "home_apps", "focus": "Apps"}
CTX = {"screen_labels": [{"node_id": "n-home", "label": "home"}, {"node_id": "n-store", "label": "apps"}]}


def _eval_result(score_eval, source="human", eval_version=None):
    rows = [{"id": "a", "ground_truth": GROUPED, "userinterface": "stb_tv", "device_model": "stb",
             "object_key": "t/screen-id/stb/a.jpg", "split": "eval", "eval_version": eval_version},
            {"id": "b", "ground_truth": dict(GROUPED, focus=None), "userinterface": "stb_tv", "device_model": "stb",
             "object_key": "t/screen-id/stb/b.jpg", "split": "eval", "eval_version": eval_version},
            {"id": "c", "ground_truth": GROUPED, "userinterface": "stb_tv", "device_model": "stb",
             "object_key": "t/screen-id/stb/c.jpg", "split": "eval", "eval_version": eval_version}]
    answers = iter([('{"label": "home"}', "tr-a"), ('{"focused": "Search"}', "tr-a-focus"),
                    ('{"label": "apps"}', "tr-b")])

    def call(prompt, image):
        text, trace = next(answers)
        return {"success": True, "content": text, "profile": "p", "fallback_used": False, "trace_id": trace,
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    def image_for(row):
        if row["id"] == "c":
            raise RuntimeError("missing")
        return b"jpeg"
    samples = score_eval.score_samples(rows, "screen-id", pinned_profile="p", call=call, image_for=image_for,
                                       context_for=lambda r: CTX)
    result = {"run_id": "screen-id-p-2026-10-04T120000Z-abc123", "created_at": "2026-10-04T12:00:00Z",
              "team_id": TEAM, "family": "screen-id", "source": source, "eval_version": eval_version,
              "profile": "p", "model": "m", "summary": score_eval.summarize(samples), "samples": samples}
    return result, rows


def test_score_eval_records_trace_ids(score_eval):
    result, _rows = _eval_result(score_eval)
    a, b, c = result["samples"]
    assert (a["trace_id"], a["focus"]["trace_id"], b["trace_id"]) == ("tr-a", "tr-a-focus", "tr-b")
    assert "trace_id" not in c  # image error: no call, no trace


def test_score_eval_builds_items_run_links_and_scores(score_eval):
    result, rows = _eval_result(score_eval)
    client = FakeLangfuse()
    summary = score_eval.push_langfuse(result, rows, lambda r: CTX, client=client)
    assert summary["dataset"] == "vpt-eval-screen-id" and summary["run"] == result["run_id"]
    assert (summary["items"], summary["linked"], summary["no_trace"], summary["scores"]) == (3, 2, 1, 3)
    assert client.datasets[0]["name"] == "vpt-eval-screen-id"
    item = client.items[0]
    assert item["id"] == "vpt-eval-screen-id:a" and item["dataset_name"] == "vpt-eval-screen-id"
    assert item["expected_output"] == GROUPED
    assert item["input"]["object_key"] == "t/screen-id/stb/a.jpg" and "- home" in item["input"]["question"]
    assert item["metadata"] == {"sample_id": "a", "split": "eval", "eval_version": None, "device_model": "stb"}
    links = [(r.run_name, r.dataset_item_id, r.trace_id) for r in client.run_items]
    assert links == [(result["run_id"], "vpt-eval-screen-id:a", "tr-a"), (result["run_id"], "vpt-eval-screen-id:b", "tr-b")]
    assert client.run_items[0].metadata["profile"] == "p"
    scores = [(s["trace_id"], s["name"], s["value"]) for s in client.scores]
    assert scores == [("tr-a", "correct", 1.0), ("tr-a", "focus_correct", 0.0), ("tr-b", "correct", 0.0)]
    assert client.flushed == 1


def test_score_eval_dataset_names_the_frozen_version(score_eval):
    result, rows = _eval_result(score_eval, source="eval-version", eval_version="eval-v1")
    client = FakeLangfuse()
    score_eval.push_langfuse(result, rows, lambda r: CTX, client=client)
    assert client.datasets[0]["name"] == "vpt-eval-screen-id-eval-v1"
    assert client.items[0]["id"] == "vpt-eval-screen-id-eval-v1:a"
    assert client.items[0]["metadata"]["eval_version"] == "eval-v1"


def test_score_eval_langfuse_failure_never_fails_the_run(score_eval, monkeypatch):
    result, rows = _eval_result(score_eval)
    down = FakeLangfuse(fail_on={"dataset"})
    assert score_eval.push_langfuse(result, rows, lambda r: CTX, client=down)["errors"]
    flaky = FakeLangfuse(fail_on={"link"})
    summary = score_eval.push_langfuse(result, rows, lambda r: CTX, client=flaky)
    assert summary["items"] == 3 and summary["linked"] == 0 and len(summary["errors"]) == 2
    assert score_eval.push_langfuse(result, rows, lambda r: CTX, skip=True, client=FakeLangfuse()) is None
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    assert score_eval.push_langfuse(result, rows, lambda r: CTX) is None
    args = score_eval.build_arg_parser().parse_args(["--no-langfuse"])
    assert args.no_langfuse is True

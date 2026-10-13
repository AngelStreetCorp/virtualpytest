"""Generic vision training hook in ``call_vision_ai`` (TASK-27 step 3d).

AI routing is served from a fixed snapshot with a fake provider client and
``record_sample`` is monkeypatched, so there is no network, no DB and no object storage.

Run: pytest tests/shared/test_training_hook_generic.py -v
"""
import base64
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, install_routing  # noqa: E402
from shared.src.lib.ai import training_samples  # noqa: E402
from shared.src.lib.utils import ai_utils  # noqa: E402

IMAGE_BYTES = b"\xff\xd8\xff\xe0fake-jpeg"
IMAGE = "data:image/jpeg;base64," + base64.b64encode(IMAGE_BYTES).decode()
ANSWER = '{"screen": "home"}'
PROMPT = "what screen?"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    clear_routing()


@pytest.fixture
def recorded(monkeypatch):
    """Routing installed, switch on, record_sample captured."""
    install_routing(monkeypatch, ANSWER)
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    captured = []

    def fake_record_sample(**kwargs):
        captured.append(kwargs)
        return "sample-123"

    monkeypatch.setattr(training_samples, "record_sample", fake_record_sample)
    return captured


def test_records_with_family_prompt_and_answer(recorded):
    result = ai_utils.call_vision_ai(PROMPT, IMAGE, "vision.menu", family="menu", team_id="team-1",
                                     device_model="stb-x")
    assert result["success"] is True
    assert result["training_sample_id"] == "sample-123"
    assert len(recorded) == 1
    kw = recorded[0]
    assert kw["family"] == "menu"
    assert kw["prompt"] == PROMPT
    assert kw["model_answer"] == {"content": ANSWER}
    assert kw["label_source"] == "none"
    assert kw["team_id"] == "team-1"
    assert kw["device_model"] == "stb-x"
    assert kw["image"] == IMAGE_BYTES


def test_family_none_records_as_other(recorded):
    ai_utils.call_vision_ai(PROMPT, IMAGE, "vision.ask", team_id="team-1", device_model="stb-x")
    assert recorded[0]["family"] == "other"


def test_no_team_id_no_record(recorded):
    result = ai_utils.call_vision_ai(PROMPT, IMAGE, "vision.menu", family="menu", device_model="stb-x")
    assert recorded == []
    assert "training_sample_id" not in result


def test_record_false_no_record(recorded):
    result = ai_utils.call_vision_ai(PROMPT, IMAGE, "vision.banner", family="banner", record=False,
                                     team_id="team-1", device_model="stb-x")
    assert recorded == []
    assert "training_sample_id" not in result


def test_result_shape_without_capture(recorded):
    result = ai_utils.call_vision_ai(PROMPT, IMAGE, "vision.describe", max_tokens=300, temperature=0.0)
    assert recorded == []
    assert result["success"] is True
    assert result["content"] == ANSWER
    assert {"success", "content", "initial_prompt", "provider_used", "usage", "profile", "via"} <= set(result)


def test_text_usage_never_records(recorded):
    result = ai_utils.call_text_ai(PROMPT, "text.translation", team_id="team-1")
    assert result["success"] is True
    assert recorded == []
    assert "training_sample_id" not in result


def test_failed_call_no_record(monkeypatch):
    install_routing(monkeypatch, RuntimeError("boom"))
    monkeypatch.setenv("TRAINING_DATA_ENABLED", "true")
    captured = []
    monkeypatch.setattr(training_samples, "record_sample", lambda **kw: captured.append(kw) or "id")
    result = ai_utils.call_vision_ai(PROMPT, IMAGE, "vision.ask", team_id="team-1", device_model="stb-x")
    assert result["success"] is False
    assert captured == []


def test_sample_links_to_its_trace(recorded, monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test")
    from shared.src.lib.ai import tracing
    monkeypatch.setattr(tracing, "get_client", lambda: None)
    result = ai_utils.call_vision_ai(PROMPT, IMAGE, "vision.menu", family="menu", team_id="team-1",
                                     device_model="stb-x")
    assert result["trace_id"]
    assert recorded[0]["source_ref"] == {"trace_id": result["trace_id"], "request_id": result["request_id"]}

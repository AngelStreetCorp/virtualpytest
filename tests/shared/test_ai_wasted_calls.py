"""TASK-93 / BUG-0514: a call that cannot succeed is stopped before it is made.

Fake clients only — no network, no keys, no DB.  Run: pytest tests/shared/test_ai_wasted_calls.py -v
"""
import os
import sys
import time

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, endpoint, install_routing, profile, route  # noqa: E402
from shared.src.lib.ai import gateway, router  # noqa: E402
from shared.src.lib.ai.provider_client import RequestNotSent  # noqa: E402


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    clear_routing()


def _hop(eid="or", preset="openrouter"):
    return router.Hop(profile={"name": "p"}, endpoint={"id": eid, "name": eid, "preset": preset, "secret_name": None})


def _paused(eid="or", left=0, step=300):
    router._no_credit[eid] = (time.time() + left, step)


def test_expired_pause_lets_exactly_one_probe_through(monkeypatch):
    # The balance reads positive (or cannot be read) while calls still 402: only ONE call may test it.
    for credit in (True, None):
        router.reset_health_for_tests()
        monkeypatch.setattr(router, "credit_available", lambda hop, c=credit: c)
        _paused(left=-1)
        hop = _hop()
        assert router.no_credit_error(hop) is None  # the probe
        assert "paused" in router.no_credit_error(hop)  # concurrent callers wait
        assert "paused" in router.no_credit_error(hop, probe=False)


def test_credit_reading_positive_does_not_forget_the_back_off(monkeypatch):
    monkeypatch.setattr(router.time, "time", lambda: 1000.0)
    monkeypatch.setattr(router, "credit_available", lambda hop: True)
    hop = _hop()
    _paused(left=-1, step=router.NO_CREDIT_STEPS_S[0])
    assert router.no_credit_error(hop) is None
    router._note_credit(hop, False, "no_credit")  # the probe was refused again
    assert router.no_credit_for("or") == router.NO_CREDIT_STEPS_S[1]
    router._note_credit(hop, True, None)  # an answered call ends it
    assert router.no_credit_for("or") == 0


def test_a_shadow_usage_never_probes_an_unreadable_balance(monkeypatch):
    monkeypatch.setattr(router, "credit_available", lambda hop: None)
    _paused(left=-1)
    assert "topped up" in router.no_credit_error(_hop(), probe=False)


def test_pause_is_shared_between_processes(monkeypatch, tmp_path):
    monkeypatch.setattr(router.time, "time", lambda: 1000.0)
    router.share_pause_for_tests(str(tmp_path / "pause.json"))
    hop = _hop()
    router._note_credit(hop, False, "no_credit")  # process A learns it
    assert router.no_credit_for("or") == router.NO_CREDIT_START_S
    router._no_credit.clear()  # process B starts with an empty memory
    router._no_credit_since.clear()
    router._pause_file_stamp = 0
    assert router.no_credit_for("or") > 0
    router._note_credit(hop, True, None)  # B sees an answer: A must see the pause end
    router._pause_file_stamp = 0
    assert router.no_credit_for("or") == 0


def test_unreachable_endpoint_is_not_called_until_its_wait_is_over(monkeypatch):
    snap = {"endpoints": {"pc": endpoint("pc", "lm")}, "profiles": {"p": profile("p", "pc", endpoint_id="pc")},
            "routes": [route("r1", "text", "p"), route("r2", "agent", "p"), route("r3", "vision", "p")]}
    calls = install_routing(monkeypatch, [__import__("requests").exceptions.ConnectionError("refused"), "late"],
                            snapshot=snap)
    for _ in range(3):
        assert gateway.complete("text.game_2048", "q")["success"] is False
    assert len(calls) == 1  # one request found it down, the next two made none
    router._down_until["pc"] = time.time() - 1
    assert gateway.complete("text.game_2048", "q")["success"] is True and len(calls) == 2


def test_a_call_our_client_refuses_is_counted_skipped_not_served(monkeypatch):
    rows = []
    calls = install_routing(monkeypatch, [RequestNotSent("needs an image")])
    monkeypatch.setattr(router, "record", lambda *a, **k: rows.append(k))
    assert gateway.complete("text.translation", "q")["success"] is False
    assert len(calls) == 1 and rows[0]["outcome"] == "skipped" and rows[0]["error_type"] == "bad_request"


def test_vlm_empty_answer_is_not_retried_on_the_same_image(monkeypatch):
    snap = {"endpoints": {"vlm": endpoint("vlm", "minimax-vlm", preset="minimax_vlm")},
            "profiles": {"p": profile("p", "vlm", endpoint_id="vlm")},
            "routes": [route("r1", "vision", "p"), route("r2", "agent", "p"), route("r3", "text", "p")]}
    calls = install_routing(monkeypatch, ["", "", ""], snapshot=snap)
    monkeypatch.setattr(router.Hop, "has_credentials", lambda self: True)
    assert gateway.complete("vision.alert_triage", "q", image_b64="aGVsbG8=")["success"] is False
    assert len(calls) == 1


def test_blank_frame_detection():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from backend_server.src.agent.core.nightwatch_handler import is_blank_frame
    flat = cv2.imencode(".jpg", np.zeros((720, 1280, 3), np.uint8))[1].tobytes()
    noisy = cv2.imencode(".jpg", (np.random.rand(90, 160, 3) * 255).astype(np.uint8))[1].tobytes()
    assert is_blank_frame(flat) and not is_blank_frame(noisy)
    assert not is_blank_frame(None) and not is_blank_frame(b"not an image")

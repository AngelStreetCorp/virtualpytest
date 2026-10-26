"""Best-effort usages (caption translation): no paid hop after a 429, empty-answer circuit breaker, OpenRouter reasoning off.

Fake provider clients only. Run: pytest tests/shared/test_ai_best_effort.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, endpoint, install_routing, profile, route  # noqa: E402
from shared.src.lib.ai import gateway, router  # noqa: E402

USAGE = "text.caption_translation"


class _RateLimit(Exception):
    status_code = 429


def _snapshot(preset="openai_compatible"):
    return {
        "endpoints": {"flat": endpoint("flat", "minimax"), "paid": endpoint("paid", "openrouter", preset=preset)},
        "profiles": {"p1": profile("p1", "flat-m3", endpoint_id="flat", fallback_profile_id="p2"),
                     "p2": profile("p2", "paid-m3", endpoint_id="paid")},
        "routes": [route("r1", "text", "p1"), route("r2", "agent", "p1"), route("r3", "vision", "p1")],
    }


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    clear_routing()


def test_rate_limited_flat_hop_is_asked_again_and_the_paid_hop_is_never_called(monkeypatch):
    # the flat hop is free: a refused request is never billed, so it is asked again on the same hop
    calls = install_routing(monkeypatch, [_RateLimit("429"), "free answer", "paid answer"], snapshot=_snapshot())
    res = gateway.complete(USAGE, "q")
    assert res["success"] is True and res["content"] == "free answer"
    assert len(calls) == 2                               # the flat hop twice, the paid hop never


def test_a_flat_hop_that_keeps_failing_never_reaches_the_paid_hop(monkeypatch):
    calls = install_routing(monkeypatch, [_RateLimit("429")] * 8, snapshot=_snapshot())
    res = gateway.complete(USAGE, "q")
    assert res["success"] is False
    assert len(calls) == 1 + gateway.RATE_LIMIT_RETRIES  # only the flat hop was asked


def test_other_usages_still_fall_back_after_a_rate_limit(monkeypatch):
    calls = install_routing(monkeypatch, [_RateLimit("429"), "paid answer"], snapshot=_snapshot())
    res = gateway.complete("text.translation", "q")
    assert res["success"] is True and len(calls) == 2


def test_skipped_hop_is_recorded_skipped_not_served(monkeypatch):
    real_record = router.record
    install_routing(monkeypatch, [_RateLimit("429")] * 8, snapshot=_snapshot())
    rows = []
    monkeypatch.setattr(router, "record", real_record)
    from shared.src.lib.ai import call_log
    monkeypatch.setattr(call_log, "submit", lambda row: rows.append(row))
    gateway.complete(USAGE, "q")
    skipped = [r for r in rows if r.get("outcome") == "skipped"]
    assert len(skipped) == 1 and skipped[0]["stop_reason"] == router.RATE_LIMIT_REASON


def test_empty_answers_open_the_breaker_and_stop_the_retries(monkeypatch):
    calls = install_routing(monkeypatch, [""] * 50, snapshot=_snapshot())
    now = [1000.0]
    monkeypatch.setattr(router.time, "time", lambda: now[0])
    trip = router.BREAKER_EMPTY_TRIP
    assert gateway.complete(USAGE, "q")["success"] is False
    assert len(calls) == 2 * trip                        # the breaker of each of the two endpoints opens on its 3rd empty
    for _ in range(5):                                    # the next captions cost nothing
        assert gateway.complete(USAGE, "q")["success"] is False
    assert len(calls) == 2 * trip
    # after the cool-down one probe per endpoint goes out; an empty answer re-opens it at once
    now[0] += router.BREAKER_COOLDOWN_S + 1
    gateway.complete(USAGE, "q")
    assert len(calls) == 2 * trip + 2
    gateway.complete(USAGE, "q")
    assert len(calls) == 2 * trip + 2


def test_an_answer_closes_the_breaker_counter(monkeypatch):
    calls = install_routing(monkeypatch, ["", "ok", "", "", "ok"], snapshot=_snapshot())
    assert gateway.complete(USAGE, "q")["content"] == "ok"
    assert gateway.complete(USAGE, "q")["content"] == "ok"
    assert len(calls) == 5


def test_breaker_does_not_touch_other_usages(monkeypatch):
    calls = install_routing(monkeypatch, [""] * 4 + ["ok"], snapshot=_snapshot())
    for _ in range(2):
        gateway.complete("text.translation", "q")
    assert len(calls) >= 4


def test_breaker_is_shared_through_the_file(monkeypatch, tmp_path):
    install_routing(monkeypatch, [""] * 10, snapshot=_snapshot())
    monkeypatch.setattr(router, "_BREAKER_FILE", str(tmp_path / "breaker.json"))
    gateway.complete(USAGE, "q")
    router._breaker.clear()   # "another process": memory empty, the file still says open
    hop = router.resolve(USAGE).hops[0]
    assert router.breaker_open_for(USAGE, hop) > 0


def test_openrouter_gets_reasoning_off_for_a_thinking_off_usage(monkeypatch):
    calls = install_routing(monkeypatch, ["ok"], snapshot=_snapshot(preset="openrouter"))
    monkeypatch.setattr(router, "_PAUSE_FILE", None)
    hop = router.resolve(USAGE).hops[1]
    assert hop.extra_body(USAGE)["reasoning"] == {"enabled": False}
    assert "reasoning" not in hop.extra_body("text.translation")

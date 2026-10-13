"""TASK-87: caller context, call-log rows and the batching sink. No DB, no network."""
import contextvars
import os
import sys
import threading
from types import SimpleNamespace

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, endpoint, install_routing, profile, route  # noqa: E402
from shared.src.lib.ai import call_log, caller, gateway, router  # noqa: E402
from shared.src.lib.ai.provider_client import CallUsage  # noqa: E402

TEAM = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    caller.clear()
    caller._process_default.clear()
    monkeypatch.setattr(caller, "_env_loaded", True)
    yield
    caller.clear()
    caller._process_default.clear()
    clear_routing()


def _resolution(monkeypatch, team=TEAM, **ctx):
    install_routing(monkeypatch, "ok")
    res = router.resolve("vision.banner", team, ctx)
    return res, res.primary


def test_bound_context_merges_and_unbinds():
    with caller.bound(origin="ui", user_id="u1"):
        with caller.bound(route="/server/x"):
            assert caller.current() == {"origin": "ui", "user_id": "u1", "route": "/server/x"}
        assert "route" not in caller.current()
    assert caller.current() == {}


def test_process_default_loses_to_a_bound_context():
    caller.set_process_default(origin="monitoring", job="discard_worker")
    assert caller.current()["origin"] == "monitoring"
    with caller.bound(origin="background", script_name="s"):
        assert caller.current() == {"origin": "background", "job": "discard_worker", "script_name": "s"}


def test_header_roundtrip_drops_route_unknown_keys_and_clips():
    with caller.bound(origin="script", route="/server/x", script_result_id="r1", host_name="h" * 500):
        value = caller.header_value()
    parsed = caller.parse_header(value)
    assert "route" not in parsed and parsed["origin"] == "script" and len(parsed["host_name"]) == 200
    assert caller.parse_header('{"origin":"x","evil":"y"}') == {"origin": "x"}
    assert caller.parse_header("not json") == {} and caller.header_value() is None


def test_threads_need_an_explicit_copy():
    seen = {}
    with caller.bound(origin="script"):
        plain = threading.Thread(target=lambda: seen.update(plain=caller.current().get("origin")))
        copied = threading.Thread(target=caller.run_in_context(lambda: seen.update(copied=caller.current().get("origin"))))
        for t in (plain, copied):
            t.start()
            t.join()
    assert seen == {"plain": None, "copied": "script"}


def test_script_child_identity_comes_from_the_environment(monkeypatch):
    monkeypatch.setattr(caller, "_env_loaded", False)
    monkeypatch.setenv("VPT_SCRIPT_REF", "zap_test.py")
    monkeypatch.setenv("VPT_CAMPAIGN_ID", "nightly")
    monkeypatch.setenv("HOST_NAME", "vpt-pi1")
    assert caller.current() == {"origin": "script", "script_name": "zap_test.py", "campaign_id": "nightly",
                                "host_name": "vpt-pi1"}


def test_build_row_carries_caller_routing_usage_and_provider_cost(monkeypatch):
    res, hop = _resolution(monkeypatch, host_name="h1", device_model="stb-x")
    usage = CallUsage(tokens_in=10, tokens_out=4, cache_read=7, cache_write=1, reasoning=2, web_searches=1, cost=0.00123)
    with caller.bound(origin="script", script_name="zap", script_result_id="r-9", user_id="u1"):
        row = call_log.build_row(res, hop, ok=True, ms=1500, tokens_in=10, tokens_out=4, fallback=True, usage=usage,
                                 attempt_index=2, extra={"images": 1, "image_bytes": 900, "parse_ok": True,
                                                         "bogus": "dropped"}, server="srv")
    assert row["usage_key"] == "vision.banner" and row["team_id"] == TEAM and row["request_id"] == res.request_id
    assert (row["origin"], row["script_name"], row["script_result_id"], row["user_id"]) == ("script", "zap", "r-9", "u1")
    assert (row["host_name"], row["device_model"]) == ("h1", "stb-x")  # routing context fills what the caller lacks
    assert (row["tokens_cache_read"], row["tokens_reasoning"], row["web_searches"]) == (7, 2, 1)
    assert row["cost"] == pytest.approx(0.00123) and row["cost_source"] == "provider"
    assert row["fallback_used"] is True and row["attempt_index"] == 2 and row["latency_ms"] == 1500
    assert row["effort_sent"] == "off" and "bogus" not in row and row["parse_ok"] is True and row["server"] == "srv"


def test_origin_defaults_to_unknown_and_eval_test_labels_win(monkeypatch):
    res, hop = _resolution(monkeypatch)
    assert call_log.build_row(res, hop, ok=True, ms=1)["origin"] == "unknown"
    pinned = router.resolve_profile("default", "vision.banner", TEAM)
    with caller.bound(origin="script"):
        assert call_log.build_row(pinned, pinned.primary, ok=True, ms=1)["origin"] == "eval"
        assert call_log.build_row(router.test_resolution(hop, "vision"), hop, ok=True, ms=1)["origin"] == "settings_test"


def test_invalid_team_id_is_dropped_not_sent(monkeypatch):
    res, hop = _resolution(monkeypatch, team="not-a-uuid")
    assert "team_id" not in call_log.build_row(res, hop, ok=True, ms=1)


def test_effort_prefers_output_config_effort(monkeypatch):
    snap = {"endpoints": {"ep-local": endpoint()},
            "profiles": {"p": profile("p", "claude", extra={"output_config": {"effort": "low"}})},
            "routes": [route("r1", "agent", "p"), route("r2", "vision", "p"), route("r3", "text", "p")]}
    install_routing(monkeypatch, "ok", snapshot=snap)
    hop = router.resolve("agent.atlas").primary
    assert hop.effort("agent.atlas") == "low"


def test_parse_ok_only_for_json_usages():
    assert call_log.parse_ok_for("vision.banner", '```json\n{"a": 1}\n```', True) is True
    assert call_log.parse_ok_for("vision.banner", "sorry, no idea", True) is False
    assert call_log.parse_ok_for("vision.ask", "plain prose", True) is None
    assert call_log.parse_ok_for("vision.banner", "", False) is None


def test_sink_batches_rows_and_never_raises(monkeypatch):
    batches = []
    monkeypatch.setattr(call_log, "_writer", lambda rows: batches.append(list(rows)))
    monkeypatch.setattr(call_log, "FLUSH_INTERVAL_S", 0.01)
    for i in range(5):
        call_log.submit({"usage_key": "x", "n": i})
    call_log.flush()
    import time
    time.sleep(0.2)
    assert sorted(r["n"] for b in batches for r in b) == [0, 1, 2, 3, 4]


def test_a_failing_write_is_retried_once_then_dropped(monkeypatch):
    attempts = []

    def boom(rows):
        attempts.append(len(rows))
        raise RuntimeError("db down")

    monkeypatch.setattr(call_log, "_writer", boom)
    monkeypatch.setattr(call_log.time, "sleep", lambda s: None)
    call_log._flush_rows([{"a": 1}, {"a": 2}])
    assert attempts == [2, 2]


def test_a_full_queue_drops_rows_without_blocking(monkeypatch):
    monkeypatch.setattr(call_log, "_ensure_thread", lambda: None)
    monkeypatch.setattr(call_log, "_queue", call_log.queue.Queue(maxsize=1))
    before = call_log.dropped()
    call_log.submit({"a": 1})
    call_log.submit({"a": 2})
    assert call_log.dropped() == before + 1


def test_reported_row_uses_the_forwarded_caller():
    with caller.bound(origin="script", host_name="vpt-pi1", script_name="zap"):
        row = call_log.reported_row({"usage": "vision.banner", "team_id": TEAM, "profile": "gpu", "endpoint": "lab",
                                     "ok": False, "ms": 700, "tokens_in": 5, "error_type": "timeout", "cost": 0.5,
                                     "request_id": "rq", "extra": {"images": 1, "nope": 1}}, "srv")
    assert (row["origin"], row["host_name"], row["error_type"], row["request_id"], row["images"]) == (
        "script", "vpt-pi1", "timeout", "rq", 1)
    assert row["cost_source"] == "provider" and "nope" not in row
    assert "error_type" not in call_log.reported_row({"usage": "u", "error_type": "made-up"})


def test_gateway_attributes_skipped_hops_and_images(monkeypatch):
    snap = {"endpoints": {"ep-local": endpoint(), "ep-host": endpoint("ep-host", "gpu", reach="host")},
            "profiles": {"p1": profile("p1", "hostgpu", endpoint_id="ep-host", fallback_profile_id="p2"),
                         "p2": profile("p2", "cloud")},
            "routes": [route("r1", "vision", "p1"), route("r2", "agent", "p1"), route("r3", "text", "p1")]}
    install_routing(monkeypatch, '{"a": 1}', snapshot=snap)
    rows = []
    monkeypatch.setattr(router, "record", lambda resolution, hop, **kw: rows.append({"hop": hop.profile_name, **kw}))
    result = gateway.complete("vision.banner", "q", image_b64="aGVsbG8=")
    assert result["success"] and result["request_id"]
    assert rows[0]["hop"] == "hostgpu" and rows[0]["outcome"] == "skipped"
    served = rows[1]
    assert served["hop"] == "cloud" and served["extra"]["images"] == 1 and served["extra"]["parse_ok"] is True


def test_gateway_records_a_cut_off_answer_as_max_tokens(monkeypatch):
    cut = SimpleNamespace(text=lambda: '{"a": ', stop_reason="length", usage=SimpleNamespace(input_tokens=5, output_tokens=9))
    install_routing(monkeypatch, [cut])
    rows = []
    monkeypatch.setattr(router, "record", lambda resolution, hop, **kw: rows.append(kw))
    gateway.complete("vision.banner", "q")
    assert rows[0]["extra"]["stop_reason"] == "max_tokens" and rows[0]["extra"]["parse_ok"] is False

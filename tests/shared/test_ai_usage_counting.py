"""TASK-87 phase 0: every billed request is counted once, with its full usage.

Fake provider clients only — no network, no DB.
Run: pytest tests/shared/test_ai_usage_counting.py -v
"""
import os
import sys
from types import SimpleNamespace

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, endpoint, install_routing, profile, route  # noqa: E402
from shared.src.lib.ai import gateway, router, tracing  # noqa: E402
from shared.src.lib.ai.provider_client import (  # noqa: E402
    ProviderResponse, ProviderUsage, _openai_usage, classify_error, openai_call_usage, response_tokens,
    response_usage,
)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    clear_routing()


def _chain():
    return {
        "endpoints": {"ep-local": endpoint()},
        "profiles": {"p1": profile("p1", "primary", fallback_profile_id="p2"), "p2": profile("p2", "backup")},
        "routes": [route("r1", "text", "p1"), route("r2", "agent", "p1"), route("r3", "vision", "p1")],
    }


def _capture(monkeypatch):
    rows = []
    monkeypatch.setattr(router, "record", lambda resolution, hop, **kw: rows.append({"hop": hop.profile_name, **kw}))
    return rows


def test_each_empty_retry_is_its_own_billed_request(monkeypatch):
    install_routing(monkeypatch, ["", "", "", "ok"], snapshot=_chain())
    rows = _capture(monkeypatch)
    result = gateway.complete("text", "x")
    assert result["content"] == "ok"
    assert [(r["hop"], r["ok"], r["error_type"]) for r in rows] == [
        ("primary", False, "empty_answer"), ("primary", False, "empty_answer"),
        ("primary", False, "empty_answer"), ("backup", True, None)]
    assert [r["attempt_index"] for r in rows] == [0, 1, 2, 3]
    assert rows[-1]["fallback"] is True and rows[0]["fallback"] is False


def test_provider_error_is_classified(monkeypatch):
    err = RuntimeError("boom")
    err.response = SimpleNamespace(status_code=429)
    install_routing(monkeypatch, [err, "ok"], snapshot=_chain())
    rows = _capture(monkeypatch)
    assert gateway.complete("text", "x")["success"] is True
    assert rows[0]["ok"] is False and rows[0]["error_type"] == "rate_limit"


def test_refusal_keeps_its_billed_tokens(monkeypatch):
    refusal = SimpleNamespace(text=lambda: "", stop_reason="refusal", stop_details=SimpleNamespace(category="x"),
                              usage=SimpleNamespace(input_tokens=7, output_tokens=1))
    install_routing(monkeypatch, [refusal, "ok"], snapshot=_chain())
    rows = _capture(monkeypatch)
    gateway.complete("text", "x")
    assert rows[0]["error_type"] == "refusal" and rows[0]["tokens_in"] == 7


def test_busy_hop_is_recorded_as_failed(monkeypatch):
    snap = _chain()
    snap["endpoints"]["ep-local"]["max_concurrency"] = 1
    install_routing(monkeypatch, "ok", snapshot=snap)
    rows = _capture(monkeypatch)
    hop = router.resolve("text").primary
    sem = gateway._semaphore(hop)
    assert sem.acquire()  # the only slot is taken
    try:
        result = gateway.complete("text", "x", timeout_s=1)
    finally:
        sem.release()
    assert result["success"] is False and result["busy"] is True
    assert rows and all(r["error_type"] == "busy" and r["ok"] is False for r in rows)


def test_response_usage_anthropic_shape():
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=100,
                            cache_creation_input_tokens=20, server_tool_use=SimpleNamespace(web_search_requests=2))
    used = response_usage(SimpleNamespace(usage=usage))
    assert (used.tokens_in, used.tokens_out, used.cache_read, used.cache_write, used.web_searches) == (10, 5, 100, 20, 2)
    assert used.cost is None
    assert response_tokens(SimpleNamespace(usage=usage)) == (10, 5)


def test_response_usage_openai_shape_keeps_provider_cost():
    raw = {"prompt_tokens": 50, "completion_tokens": 8, "cost": 0.0012,
           "prompt_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 4},
           "completion_tokens_details": {"reasoning_tokens": 6}}
    used = response_usage(ProviderResponse(content=[], usage=_openai_usage(raw)))
    assert (used.tokens_in, used.tokens_out, used.cache_read, used.cache_write, used.reasoning) == (50, 8, 30, 4, 6)
    assert used.cost == pytest.approx(0.0012)
    assert openai_call_usage(raw).cost == pytest.approx(0.0012)
    assert response_usage(ProviderResponse(content=[], usage=ProviderUsage())).cost is None
    assert response_usage(SimpleNamespace()).tokens_in == 0


def test_classify_error():
    def http(code):
        e = RuntimeError("x")
        e.response = SimpleNamespace(status_code=code)
        return e
    assert [classify_error(http(c)) for c in (402, 401, 429, 503, 400)] == [
        "no_credit", "auth", "rate_limit", "server", "bad_request"]
    assert classify_error(ValueError("?")) == "bad_request"  # our own validation (1g)


def test_traced_create_counts_the_request_when_given_a_resolution(monkeypatch):
    install_routing(monkeypatch, "ok")
    rows = _capture(monkeypatch)
    resolution = router.resolve("text")
    hop = resolution.primary
    ok_client = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: SimpleNamespace(
        content=[], text=lambda: "hi", usage=SimpleNamespace(input_tokens=4, output_tokens=2))))
    tracing.traced_create(ok_client, hop, [], resolution=resolution, model="m")
    bad_client = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: (_ for _ in ()).throw(RuntimeError("x"))))
    with pytest.raises(RuntimeError):
        tracing.traced_create(bad_client, hop, [], resolution=resolution, model="m")
    tracing.traced_create(ok_client, hop, [], model="m")  # no resolution: traced only
    assert [(r["ok"], r.get("tokens_in")) for r in rows] == [(True, 4), (False, None)]


def test_classify_error_names_our_own_validation_and_bad_json():
    # 1g: MiniMax VLM without an image / a missing key was "other"; it is a bad request.
    import json
    assert classify_error(ValueError("The MiniMax VLM endpoint needs an image")) == "bad_request"
    assert classify_error(json.JSONDecodeError("x", "", 0)) == "server"
    assert classify_error(RuntimeError("boom")) == "other"

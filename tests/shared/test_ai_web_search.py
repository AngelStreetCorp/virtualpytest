"""Web-grounded AI calls (TASK-05): per-provider web search, sources, never ungrounded.

Fake provider clients only — no network, no keys, no DB.

Run: pytest tests/shared/test_ai_web_search.py -v
"""
import os
import sys
from types import SimpleNamespace

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, endpoint, install_routing, profile, route  # noqa: E402
from shared.src.lib.ai import gateway, router, usages  # noqa: E402
from shared.src.lib.ai.config import PRESETS  # noqa: E402
from shared.src.lib.ai.provider_client import (  # noqa: E402
    create_client,
    response_sources,
    response_text,
    single_completion,
)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    clear_routing()


def _snapshot(*chain):
    """Endpoints/profiles for ``chain`` = [(preset, name), ...], each falling back to the next."""
    endpoints, profiles = {}, {}
    for i, (preset, name) in enumerate(chain):
        endpoints[f"ep{i}"] = endpoint(f"ep{i}", name, preset=preset, secret_name=None)
        profiles[f"p{i}"] = profile(f"p{i}", name, endpoint_id=f"ep{i}",
                                    fallback_profile_id=f"p{i + 1}" if i + 1 < len(chain) else None)
    routes = [route("r-text", "text", "p0"), route("r-agent", "agent", "p0"), route("r-vision", "vision", "p0")]
    return {"endpoints": endpoints, "profiles": profiles, "routes": routes}


def test_web_usages_need_web_and_presets_declare_a_mechanism():
    assert "web" in usages.CAPABILITIES
    assert gateway.needs_web("text.web")
    assert not gateway.needs_web("text") and not gateway.needs_web("vision.banner")
    assert {name for name, p in PRESETS.items() if p.web_search} == {"anthropic", "openrouter", "google"}


def test_web_usage_skips_presets_that_cannot_search(monkeypatch):
    calls = install_routing(monkeypatch, "grounded answer",
                            snapshot=_snapshot(("minimax", "mm"), ("openrouter", "or")))
    result = gateway.complete("text.web", "who plays?")
    assert result["success"] is True and result["profile"] == "or"
    assert len(calls) == 1
    assert calls[0]["extra_body"]["plugins"] == [{"id": "web", "max_results": 3}]


def test_web_usage_never_falls_back_to_an_ungrounded_model(monkeypatch):
    calls = install_routing(monkeypatch, "invented lineup", snapshot=_snapshot(("openai_compatible", "local")))
    result = gateway.complete("text.web", "lineups tonight?")
    assert result["success"] is False and "cannot search the web" in result["error"]
    assert calls == []


def test_non_web_usage_sends_no_search(monkeypatch):
    calls = install_routing(monkeypatch, "ok", snapshot=_snapshot(("openrouter", "or")))
    gateway.complete("text", "hi")
    assert "plugins" not in (calls[0]["extra_body"] or {}) and calls[0]["tools"] == []


def test_anthropic_web_tool_and_answer_after_last_search():
    sent = {}
    fake_sdk = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: sent.update(kw) or SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Let me search.", citations=None),
            SimpleNamespace(type="server_tool_use"),
            SimpleNamespace(type="web_search_tool_result", content=[
                SimpleNamespace(url="https://a.test/match", title="Match")]),
            SimpleNamespace(type="text", text='{"venue": "Fortuna Arena"}', citations=[
                SimpleNamespace(url="https://b.test/venue", title="Venue")]),
        ],
        usage=SimpleNamespace(input_tokens=5, output_tokens=5),
    )))
    client = create_client("anthropic", "sk")
    client._client = fake_sdk
    resp = single_completion(client, model="claude-x", prompt="venue?", web_search="anthropic_tool")
    assert sent["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    assert "tool_choice" not in sent
    assert response_text(resp) == '{"venue": "Fortuna Arena"}'
    assert [s["url"] for s in response_sources(resp)] == ["https://a.test/match", "https://b.test/venue"]


def test_openrouter_citations_become_sources(monkeypatch):
    sent = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "answer", "annotations": [
                {"type": "url_citation", "url_citation": {"url": "https://c.test", "title": "C"}}]}}], "usage": {}}

    import shared.src.lib.ai.provider_client as pc
    monkeypatch.setattr(pc.requests, "post", lambda url, headers, json, timeout: sent.update(json) or _Resp())
    resp = single_completion(create_client("openrouter", "sk"), model="m", prompt="q", web_search="openrouter_plugin")
    assert sent["plugins"] == [{"id": "web", "max_results": 3}]
    assert response_sources(resp) == [{"url": "https://c.test", "title": "C"}]


def test_google_grounding_tool_and_sources(monkeypatch):
    sent = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "answer"}]},
                                    "groundingMetadata": {"groundingChunks": [
                                        {"web": {"uri": "https://g.test", "title": "G"}}]}}]}

    import shared.src.lib.ai.provider_client as pc
    monkeypatch.setattr(pc.requests, "post", lambda url, params, headers, json, timeout: sent.update(json) or _Resp())
    resp = single_completion(create_client("google", "k"), model="gemini", prompt="q", web_search="google_grounding")
    assert sent["tools"] == [{"google_search": {}}]
    assert response_sources(resp) == [{"url": "https://g.test", "title": "G"}]


def test_a_feature_usage_under_text_web_inherits_the_web_need():
    key = "text.web.test_feature"
    usages.register(usages.feature_usage(key, "Test", "feature-owned key", "text.web", output="json"))
    try:
        assert gateway.needs_web(key) and usages.lineage(key) == [key, "text.web", "text"]
        with pytest.raises(ValueError, match="already defined"):
            usages.register(usages.feature_usage("text.web", "X", "clash", "text"))
    finally:
        usages.USAGES.pop(key, None)


# ---------------------------------------------------------------- call budget (timeout_s)
def test_full_endpoint_returns_busy_within_the_budget_without_calling(monkeypatch):
    snap = _snapshot(("openai_compatible", "pc"))
    snap["endpoints"]["ep0"]["max_concurrency"] = 1
    calls = install_routing(monkeypatch, "ok", snapshot=snap)
    hop = router.resolve("text").hops[0]
    sem = gateway._semaphore(hop)
    sem.acquire()                                    # someone else holds the only slot
    try:
        result = gateway.complete("text", "hi", timeout_s=1)
    finally:
        sem.release()
    assert result["success"] is False and result["busy"] is True and "busy" in result["error"]
    assert calls == []


def test_read_timeout_within_the_budget_is_busy_not_down(monkeypatch):
    import requests
    install_routing(monkeypatch, requests.exceptions.ReadTimeout("slow"), snapshot=_snapshot(("openai_compatible", "pc")))
    result = gateway.complete("text", "hi", timeout_s=30)
    assert result["busy"] is True
    assert router.endpoint_down_for("ep0") == 0      # saturated is not unreachable


def test_no_budget_keeps_the_old_behaviour(monkeypatch):
    import requests
    install_routing(monkeypatch, requests.exceptions.ReadTimeout("slow"), snapshot=_snapshot(("openai_compatible", "pc")))
    assert gateway.complete("text", "hi")["busy"] is False


def test_host_sends_the_budget_and_waits_only_a_bit_longer(monkeypatch):
    sent = {}
    monkeypatch.setattr(gateway, "_local_routing", False)
    monkeypatch.setattr(gateway, "_server_post", lambda path, payload, timeout: sent.update(payload=payload, wait=timeout)
                        or {"success": True, "content": "x"})
    gateway.complete("text", "hi", timeout_s=30)
    assert sent["payload"]["timeout_s"] == 30 and sent["wait"] == 2 * 30 + gateway.BUDGET_MARGIN_S


def test_host_call_with_the_server_down_returns_unreachable_not_a_crash(monkeypatch):
    """BUG-0412: two stacked `except` clauses left `data` unset on a non-timeout error (connection
    refused while the server restarts), so the host call raised UnboundLocalError."""
    monkeypatch.setattr(gateway, "_local_routing", False)

    def refused(path, payload, timeout):
        raise ConnectionRefusedError("[Errno 111] Connection refused")
    monkeypatch.setattr(gateway, "_server_post", refused)
    for budget in (None, 30):
        result = gateway.complete("text", "hi", timeout_s=budget)
        assert result["success"] is False and "unreachable" in result["error"] and not result.get("busy")

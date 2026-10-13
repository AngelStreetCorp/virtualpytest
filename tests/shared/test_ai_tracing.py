"""Every AI call is traced to Langfuse (shared/src/lib/ai/tracing.py).

A fake Langfuse client records traces and generations; no network.

Run: pytest tests/shared/test_ai_tracing.py -v
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
from shared.src.lib.ai import gateway, router, tracing  # noqa: E402

IMAGE_B64 = "aGVsbG8gd29ybGQgdGhpcyBpcyBhbiBpbWFnZQ=="


class FakeTrace:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.generations = []

    def generation(self, **kwargs):
        self.generations.append(kwargs)


class FakeLangfuse:
    def __init__(self):
        self.traces = []

    def trace(self, **kwargs):
        t = FakeTrace(kwargs)
        self.traces.append(t)
        return t


@pytest.fixture
def langfuse(monkeypatch):
    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "get_client", lambda: fake)
    yield fake
    clear_routing()


def _pc_snapshot():
    return {
        "endpoints": {"pc": endpoint("pc", "lmstudio-pc"),
                      "cloud": endpoint("cloud", "openrouter", preset="openrouter")},
        "profiles": {"p-pc": profile("p-pc", "qwen-pc", endpoint_id="pc", fallback_profile_id="p-cloud"),
                     "p-cloud": profile("p-cloud", "gpt-cloud", endpoint_id="cloud")},
        "routes": [route("r1", "text", "p-pc"), route("r2", "agent", "p-cloud"), route("r3", "vision", "p-pc")],
    }


def test_successful_call_is_one_trace_one_generation(monkeypatch, langfuse):
    install_routing(monkeypatch, "hello world", snapshot=_pc_snapshot())
    result = gateway.complete("text.translation", "bonjour", team_id="team-1")
    assert result["success"]
    (trace,) = langfuse.traces
    meta = trace.kwargs["metadata"]
    assert trace.kwargs["name"] == "AI text.translation"
    assert meta["usage"] == "text.translation" and meta["profile"] == "qwen-pc" and meta["endpoint"] == "lmstudio-pc"
    assert meta["team_id"] == "team-1" and meta["fallback_used"] is False and meta["ok"] is True
    assert "usage:text.translation" in trace.kwargs["tags"] and "profile:qwen-pc" in trace.kwargs["tags"]
    assert trace.kwargs["input"] == {"prompt": "bonjour"} and trace.kwargs["output"] == "hello world"
    (gen,) = trace.generations
    assert gen["model"] == "qwen3-vl-8b" and gen["level"] == "DEFAULT" and gen["output"] == "hello world"
    assert gen["usage"] == {"input": 3, "output": 2, "unit": "TOKENS", "total_cost": 0.0}  # local PC: free


def test_fallback_shows_the_failed_attempt_first(monkeypatch, langfuse):
    import requests
    install_routing(monkeypatch, [requests.exceptions.ConnectionError("PC off"), "cloud answer"],
                    snapshot=_pc_snapshot())
    gateway.complete("text.translation", "bonjour")
    (trace,) = langfuse.traces
    assert trace.kwargs["metadata"]["profile"] == "gpt-cloud"
    assert trace.kwargs["metadata"]["fallback_used"] is True
    failed, served = trace.generations
    assert failed["level"] == "ERROR" and "PC off" in failed["status_message"]
    assert failed["metadata"]["endpoint"] == "lmstudio-pc"
    assert served["level"] == "DEFAULT" and served["metadata"]["fallback"] is True


def test_routing_failure_is_traced(monkeypatch, langfuse):
    install_routing(monkeypatch)
    result = gateway.complete("vision.nope", "x")
    assert result["success"] is False
    (trace,) = langfuse.traces
    assert trace.kwargs["metadata"]["ok"] is False and "Unknown AI usage" in trace.kwargs["output"]
    assert trace.generations == []


def test_images_are_never_uploaded(monkeypatch, langfuse):
    install_routing(monkeypatch, "a cat", snapshot=_pc_snapshot())
    gateway.complete("vision.ask", "what is this?", image_b64=IMAGE_B64, media_type="image/png")
    (trace,) = langfuse.traces
    assert IMAGE_B64 not in repr(trace.kwargs) and IMAGE_B64 not in repr(trace.generations)
    assert trace.kwargs["input"]["image"] == "[image omitted: image/png]"


def test_scrub_messages_replaces_image_blocks():
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "hi"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": IMAGE_B64}},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{IMAGE_B64}"}},
    ]}]
    scrubbed = tracing.scrub_messages(messages)
    assert IMAGE_B64 not in repr(scrubbed)
    assert scrubbed[0]["content"][0] == {"type": "text", "text": "hi"}
    assert scrubbed[0]["content"][2]["note"] == "[image omitted: image/png]"


def test_langfuse_errors_never_break_the_call(monkeypatch):
    class Broken:
        def trace(self, **kwargs):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(tracing, "get_client", lambda: Broken())
    install_routing(monkeypatch, "still fine", snapshot=_pc_snapshot())
    try:
        assert gateway.complete("text", "x")["content"] == "still fine"
    finally:
        clear_routing()


def test_traced_create_records_tool_calls_and_errors():
    hop = router.Hop(profile=profile(), endpoint=endpoint())
    tool_block = SimpleNamespace(type="tool_use", name="list_hosts", input={}, id="t1")
    ok_client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        content=[tool_block], usage=SimpleNamespace(input_tokens=5, output_tokens=1))))
    attempts = []
    tracing.traced_create(ok_client, hop, attempts, model="m")
    assert attempts[0].ok and "tool list_hosts" in attempts[0].output and attempts[0].tokens == (5, 1)

    def boom(**kw):
        raise RuntimeError("rate limited")
    bad_client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    with pytest.raises(RuntimeError):
        tracing.traced_create(bad_client, hop, attempts, model="m")
    assert attempts[1].ok is False and "rate limited" in attempts[1].error


def test_tracing_off_without_langfuse_host(monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setattr(tracing, "_client", None)
    assert tracing.get_client() is None


def test_enabled_is_read_at_call_time(monkeypatch):
    # The server imports the AI modules before loading .env: the switch must not be frozen at import.
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    assert tracing.enabled() is False
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test")
    assert tracing.enabled() is True


def test_trace_id_is_returned_and_used_as_the_langfuse_id(monkeypatch, langfuse):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test")
    install_routing(monkeypatch, "ok", snapshot=_pc_snapshot())
    result = gateway.complete("vision.ask", "q", image_b64=IMAGE_B64)
    (trace,) = langfuse.traces
    assert result["trace_id"] and trace.kwargs["id"] == result["trace_id"]


def test_scoring_calls_are_labelled_eval(monkeypatch, langfuse):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test")
    install_routing(monkeypatch, "banner json", snapshot=_pc_snapshot())
    recorded = []
    monkeypatch.setattr(router, "record", lambda res, hop, **kw: recorded.append(res.stats_label))
    res = router.resolve_profile("qwen-pc", "vision.banner")
    gateway.execute(res, "read the banner", image_b64=IMAGE_B64)
    assert recorded == ["eval:vision.banner"]
    assert langfuse.traces[0].kwargs["name"] == "AI eval:vision.banner"

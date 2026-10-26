"""Anthropic prompt caching: where the breakpoints go and how cached tokens are counted."""
from types import SimpleNamespace

from shared.src.lib.ai.provider_client import AnthropicProviderClient, cache_breakpoints, single_completion
from shared.src.lib.game.clashofclans import llm_budget

EPHEMERAL = {"type": "ephemeral"}


class _Messages:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return {"ok": True}


def _client(provider="anthropic"):
    client = AnthropicProviderClient(api_key="test-key", provider=provider)
    client._client = SimpleNamespace(messages=_Messages())
    return client


def _sent(client):
    return client._client.messages.kwargs


def test_one_shot_vision_call_caches_the_system_prompt_not_the_screenshot():
    client = _client()
    single_completion(client, model="claude-haiku-5-5", prompt="Next action?", image_b64="QUJD", system="rules")
    sent = _sent(client)
    assert sent["system"] == [{"type": "text", "text": "rules", "cache_control": EPHEMERAL}]
    content = sent["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "text"]  # the changing parts, after the cached prefix
    assert not any("cache_control" in b for b in content)
    assert "cache_control" not in (sent.get("extra_body") or {})  # no automatic breakpoint on a unique tail


def test_conversation_gets_the_automatic_breakpoint():
    client = _client()
    client.create(model="m", max_tokens=10, system=[{"type": "text", "text": "s", "cache_control": EPHEMERAL}],
                  messages=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                            {"role": "user", "content": "c"}], tools=[])
    assert _sent(client)["extra_body"]["cache_control"] == EPHEMERAL


def test_no_automatic_breakpoint_when_four_explicit_ones_are_used():
    client = _client()
    tools = [{"name": f"t{i}", "cache_control": EPHEMERAL} for i in range(3)]
    kwargs = dict(model="m", max_tokens=10, system=[{"type": "text", "text": "s", "cache_control": EPHEMERAL}],
                  messages=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}], tools=tools)
    assert cache_breakpoints(kwargs) == 4
    client.create(**kwargs)
    assert "extra_body" not in _sent(client)


def test_anthropic_compatible_endpoints_do_not_get_the_automatic_field():
    client = _client(provider="minimax")
    client.create(model="m", max_tokens=10, system=[], tools=[],
                  messages=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    assert "extra_body" not in _sent(client)


def test_cached_prompt_is_metered_at_the_cache_prices():
    price = {"price_in": 0.1, "price_out": 0.5, "price_cache_read": 0.01, "price_cache_write": 0.125}
    # 3000-token prompt, 2000 of them read from the cache: 1000 + 2000 * 0.1
    assert llm_budget.input_equivalent(price, 3000, cache_read=2000) == 1200
    assert llm_budget.input_equivalent(price, 3000, cache_write=2000) == 1000 + 2500
    assert llm_budget.input_equivalent({"price_in": 0.1}, 3000, cache_read=2000) == 3000  # no cache price: plain


def test_agent_tool_breakpoints_are_capped():
    from backend_server.src.agent.core import manager

    tools = [{"name": f"t{i}"} for i in range(6)]
    fake = SimpleNamespace(tool_bridge=SimpleNamespace(get_tool_definitions=lambda names: tools),
                           _active_skill=SimpleNamespace(get_cacheable_tools=lambda: ["t0", "t1", "t2", "t3"]),
                           logger=SimpleNamespace(debug=lambda *a: None))
    out = manager.QAManagerAgent._build_cached_tools(fake, [])
    marked = [t["name"] for t in out if t.get("cache_control")]
    assert len(marked) == manager.TOOL_CACHE_BREAKPOINTS and marked[-1] == "t5"

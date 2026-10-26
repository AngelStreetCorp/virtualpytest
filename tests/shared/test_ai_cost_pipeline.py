"""Cost pipeline: provider cost asked for and parsed, OpenRouter list prices, flat plan, Langfuse gets our cost."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from shared.src.lib.ai import price_sync, prices, tracing  # noqa: E402
from shared.src.lib.ai.provider_client import CallUsage, OpenAICompatibleProviderClient  # noqa: E402

OR = {"id": "e1", "name": "or", "preset": "openrouter", "base_url": "https://openrouter.ai/api/v1"}
MM = {"id": "e2", "name": "minimax", "preset": "minimax"}
OR_LIST = [{"id": "openai/gpt-4.1-mini", "pricing": {"prompt": "0.0000004", "completion": "0.0000016",
                                                      "input_cache_read": "0.0000001"}},
           {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}}]


def _hop(ep, model="m"):
    return SimpleNamespace(endpoint_name=ep["name"], model=model, endpoint=ep, preset=ep["preset"], profile_name="p")


def test_openrouter_request_asks_for_cost_and_reply_cost_is_parsed(monkeypatch):
    sent = {}

    class Resp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.00042}}

    import shared.src.lib.ai.provider_client as pc
    monkeypatch.setattr(pc.requests, "post", lambda url, **kw: sent.update(kw) or Resp())
    client = OpenAICompatibleProviderClient("openrouter", "k", "https://openrouter.ai/api/v1")
    out = client.create(model="m", max_tokens=5, system=[], messages=[{"role": "user", "content": "x"}], tools=[])
    assert sent["json"]["usage"] == {"include": True}
    assert out.usage.cost == 0.00042


def test_openrouter_list_pricing_is_converted_to_per_million():
    assert price_sync.openrouter_per_million(OR_LIST[0]) == {"price_in": 0.4, "price_out": 1.6, "price_cache_read": 0.1}
    assert price_sync.openrouter_per_million(OR_LIST[1]) is None  # variable-price router


def test_plan_prices_openrouter_endpoints_from_the_openrouter_list_and_skips_plan_endpoints():
    profiles = [{"endpoint_id": "e1", "model": "openai/gpt-4.1-mini:online"}, {"endpoint_id": "e2", "model": "MiniMax-M2"}]
    rows = price_sync.plan([], [OR, MM], profiles, [], OR_LIST)
    assert [(r["endpoint"], r["price_in"], r["note"]) for r in rows] == [("or", 0.4, "source:openrouter")]


def test_manual_price_is_never_overwritten():
    profiles = [{"endpoint_id": "e1", "model": "openai/gpt-4.1-mini"}]
    manual = [{"endpoint": "or", "model": "openai/gpt-4.1-mini", "valid_from": "2026-01-01", "note": "negotiated"}]
    assert price_sync.plan([], [OR], profiles, manual, OR_LIST) == []


def test_flat_plan_endpoint_costs_zero_and_a_typed_price_still_wins():
    prices.set_for_tests([])
    try:
        assert prices.cost_for(_hop(MM), 1000, 100) == (0.0, 0.0)
        assert prices.resolve(_hop(MM), 1000, 100) == (0.0, "price_table")
        prices.set_for_tests([{"endpoint": "minimax", "model": "*", "price_in": 1, "price_out": 1,
                               "valid_from": "2026-01-01"}])
        assert prices.cost_for(_hop(MM), 1_000_000, 0)[0] == 1.0
    finally:
        prices.set_for_tests(None)


def test_provider_cost_beats_the_price_table_and_sources_are_named():
    assert prices.resolve(_hop(OR), 10, 10, CallUsage(cost=0.5)) == (0.5, "provider")
    names = ("source:openrouter", "source:langfuse", "source:plan", "mine", None)
    assert [prices.source_of(n) for n in names] == ["openrouter", "langfuse", "plan", "manual", "manual"]


def test_langfuse_generation_receives_our_cost(monkeypatch):
    seen = []

    class T:
        def generation(self, **kw):
            seen.append(kw)

    class C:
        def trace(self, **kw):
            return T()

    monkeypatch.setattr(tracing, "get_client", lambda: C())
    prices.set_for_tests([])
    try:
        att = tracing.Attempt(_hop(OR))
        att.finish(ok=True, output="x", tokens=(10, 2), usage=CallUsage(tokens_in=10, tokens_out=2, cost=0.00042))
        tracing.trace_call(name="n", usage="u", input="i", attempts=[att])
        assert seen[0]["usage"] == {"input": 10, "output": 2, "unit": "TOKENS", "total_cost": 0.00042}
        att2 = tracing.Attempt(_hop(MM))
        att2.finish(ok=True, output="x", tokens=(10, 2))
        tracing.trace_call(name="n", usage="u", input="i", attempts=[att2])
        assert seen[1]["usage"]["total_cost"] == 0.0
    finally:
        prices.set_for_tests(None)


def test_a_synced_price_never_bills_the_coding_plan_but_a_typed_one_does():
    """The MiniMax coding plan is a subscription: a price row synced from Langfuse must not bill it."""
    synced = {"endpoint": "minimax", "model": "minimax-m2.7-highspeed", "price_in": 0.25, "price_out": 1.0,
              "valid_from": "2026-01-01", "note": "source:langfuse"}
    prices.set_for_tests([synced], [])
    try:
        assert prices.cost_for(_hop(MM, model="minimax-m2.7-highspeed"), 1_000_000, 1_000_000) == (0.0, 0.0)
        prices.set_for_tests([dict(synced, note="negotiated")], [])
        assert prices.cost_for(_hop(MM, model="minimax-m2.7-highspeed"), 1_000_000, 1_000_000) == (1.25, 0.0)
    finally:
        prices.set_for_tests(None)


def test_a_call_without_tokens_is_free_on_the_plan_and_unknown_on_a_metered_endpoint():
    prices.set_for_tests([], [])
    try:
        assert prices.cost_for(_hop(MM), 0, 0) == (0.0, 0.0)   # the coding plan: free whatever the size
        assert prices.cost_for(_hop(OR), 0, 0) is None          # a metered endpoint: unknown, never 0
    finally:
        prices.set_for_tests(None)


def test_only_models_langfuse_lacks_are_pushed():
    rows = [{"model": "claude-sonnet-4", "price_in": 3, "price_out": 15},
            {"model": "brand-new", "price_in": 1, "price_out": 2}]
    lf = [{"modelName": "claude-sonnet-4", "matchPattern": "(?i)^claude-sonnet-4$", "inputPrice": 1, "outputPrice": 1}]
    assert [r["model"] for r in price_sync.missing_in_langfuse(rows, lf)] == ["brand-new"]

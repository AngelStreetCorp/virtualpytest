"""TASK-87 phase 3: cost at write time from the dated price table."""
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, endpoint, install_routing, profile, route  # noqa: E402
from shared.src.lib.ai import call_log, prices, router  # noqa: E402
from shared.src.lib.ai.provider_client import CallUsage  # noqa: E402

D = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # noqa: E731


def row(model="m", valid_from="2026-01-01", endpoint_name="local", **kw):
    return {"endpoint": endpoint_name, "model": model, "price_in": 3.0, "price_out": 15.0, "price_cache_read": None,
            "price_cache_write": None, "price_web_search": None, "valid_from": valid_from, **kw}


def test_latest_valid_price_wins_and_history_is_not_rewritten():
    rows = [row(valid_from="2026-01-01"), row(valid_from="2026-06-01", price_in=1.0)]
    assert prices.price_for("local", "m", D("2026-03-01"), rows)["price_in"] == 3.0   # a call made in March
    assert prices.price_for("local", "m", D("2026-07-01"), rows)["price_in"] == 1.0
    assert prices.price_for("local", "m", D("2025-12-31"), rows) is None


def test_exact_model_beats_endpoint_wildcard_and_unknown_is_none():
    rows = [row(model="*", price_in=0.0, price_out=0.0), row(model="m", price_in=2.0)]
    assert prices.price_for("local", "m", D("2026-07-01"), rows)["price_in"] == 2.0
    assert prices.price_for("local", "other", D("2026-07-01"), rows)["price_in"] == 0.0
    assert prices.price_for("cloud", "m", D("2026-07-01"), rows) is None


def test_compute_anthropic_shape_separates_cache_tokens():
    price = row(price_cache_read=0.3, price_cache_write=3.75, price_web_search=0.01)
    cost, saved = prices.compute(price, tokens_in=1000, tokens_out=200, cache_read=10_000, cache_write=2000, web_searches=2)
    assert cost == pytest.approx((1000 * 3 + 10_000 * 0.3 + 2000 * 3.75 + 200 * 15) / 1e6 + 0.02)
    assert saved == pytest.approx(10_000 * (3.0 - 0.3) / 1e6)


def test_compute_openai_shape_counts_cached_tokens_inside_prompt_tokens():
    price = row(price_cache_read=0.3)
    cost, _ = prices.compute(price, tokens_in=11_000, tokens_out=0, cache_read=10_000, input_includes_cache=True)
    assert cost == pytest.approx((1000 * 3 + 10_000 * 0.3) / 1e6)


def test_zero_price_is_a_price_and_missing_price_is_no_cost(monkeypatch):
    install_routing(monkeypatch, "ok", snapshot={
        "endpoints": {"ep-local": endpoint()}, "profiles": {"p": profile("p", "gpu", model="qwen")},
        "routes": [route("r1", "vision", "p"), route("r2", "agent", "p"), route("r3", "text", "p")]})
    res = router.resolve("vision.banner", None)
    hop = res.primary
    # A local endpoint (keyless OpenAI-compatible server) is free even with no price row (TASK-87 R3) ...
    free = call_log.build_row(res, hop, ok=True, ms=1, tokens_in=500, tokens_out=50)
    assert free["cost"] == 0.0 and free["cost_source"] == "price_table"
    # ... a cloud endpoint with no price row stays "no price".
    install_routing(monkeypatch, "ok", snapshot={
        "endpoints": {"ep-local": endpoint(preset="openrouter", base_url="https://openrouter.ai/api/v1")},
        "profiles": {"p": profile("p", "gpu", model="qwen")},
        "routes": [route("r1", "vision", "p"), route("r2", "agent", "p"), route("r3", "text", "p")]})
    cloud = router.resolve("vision.banner", None)
    unpriced = call_log.build_row(cloud, cloud.primary, ok=True, ms=1, tokens_in=500, tokens_out=50)
    assert "cost" not in unpriced and unpriced["cost_source"] == "none"
    prices.set_for_tests([row(model="*", endpoint_name="local", price_in=0.0, price_out=0.0)])
    zero = call_log.build_row(cloud, cloud.primary, ok=True, ms=1, tokens_in=500, tokens_out=50)
    assert zero["cost"] == 0.0 and zero["cost_source"] == "price_table"


def test_provider_cost_beats_the_table_and_cache_savings_are_stored(monkeypatch):
    install_routing(monkeypatch, "ok", snapshot={
        "endpoints": {"ep-local": endpoint(preset="anthropic")}, "profiles": {"p": profile("p", "claude", model="m")},
        "routes": [route("r1", "vision", "p"), route("r2", "agent", "p"), route("r3", "text", "p")]})
    prices.set_for_tests([row(price_cache_read=0.3)])
    res = router.resolve("vision.banner", None)
    used = CallUsage(tokens_in=100, tokens_out=10, cache_read=5000, cost=0.5)
    r = call_log.build_row(res, res.primary, ok=True, ms=1, tokens_in=100, tokens_out=10, usage=used)
    assert r["cost"] == 0.5 and r["cost_source"] == "provider" and r["cache_saved"] == pytest.approx(5000 * 2.7 / 1e6)
    avoided = call_log.build_row(res, res.primary, ok=True, ms=0, outcome="avoided")
    assert "cost" not in avoided and "cache_saved" not in avoided  # an avoided call has no tokens, no price
    clear_routing()


def test_reported_host_call_is_priced_from_the_table():
    prices.set_for_tests([row(model="qwen", endpoint_name="lab-gpu", price_in=0.1, price_out=0.2)])
    r = call_log.reported_row({"usage": "vision.banner", "profile": "p", "endpoint": "lab-gpu", "model": "qwen",
                               "ok": True, "tokens_in": 1_000_000, "tokens_out": 1_000_000})
    assert r["cost"] == pytest.approx(0.3) and r["cost_source"] == "price_table"

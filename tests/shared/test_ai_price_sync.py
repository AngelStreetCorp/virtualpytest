"""TASK-87 round 2 R3: prices from Langfuse's model list, manual rows win, local endpoints are free (pure)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from shared.src.lib.ai import price_sync, prices  # noqa: E402

LF = [{"modelName": "claude-sonnet-4", "matchPattern": "(?i)^(anthropic/)?claude-sonnet-4$",
       "prices": {"input": {"price": 0.000003}, "output": {"price": 0.000015}, "input_cache_read": {"price": 0.0000003}}},
      {"modelName": "gpt-x", "matchPattern": "(?i)^gpt-x$", "inputPrice": 0.000001, "outputPrice": 0.000002}]
CLOUD = {"id": "e1", "name": "or", "preset": "openai", "base_url": "https://api.openai.com/v1"}  # Langfuse path
LOCAL = {"id": "e2", "name": "gpu", "preset": "openai_compatible", "base_url": "http://192.168.0.5:8000/v1"}


def test_per_million_handles_the_prices_map_and_the_flat_fields():
    assert price_sync._per_million(LF[0]) == {"price_in": 3.0, "price_out": 15.0, "price_cache_read": 0.3}
    assert price_sync._per_million(LF[1]) == {"price_in": 1.0, "price_out": 2.0}
    assert price_sync._per_million({"modelName": "x"}) is None


def test_plan_writes_cloud_models_only_and_never_over_a_manual_price():
    profiles = [{"endpoint_id": "e1", "model": "anthropic/claude-sonnet-4"}, {"endpoint_id": "e1", "model": "gpt-x"},
                {"endpoint_id": "e2", "model": "claude-sonnet-4"}, {"endpoint_id": "e1", "model": "unknown-model"}]
    manual = [{"endpoint": "or", "model": "gpt-x", "valid_from": "2026-01-01", "note": None}]
    rows = price_sync.plan(LF, [CLOUD, LOCAL], profiles, manual)
    assert [(r["endpoint"], r["model"], r["price_in"]) for r in rows] == [("or", "anthropic/claude-sonnet-4", 3.0)]
    assert rows[0]["note"] == price_sync.SOURCE_NOTE
    again = [{**rows[0], "valid_from": "2026-10-13"}]  # unchanged price: no new row
    assert price_sync.plan(LF, [CLOUD, LOCAL], profiles, manual + again) == []
    wildcard = [{"endpoint": "or", "model": "*", "valid_from": "2026-01-01", "note": None, "price_in": 0, "price_out": 0}]
    assert price_sync.plan(LF, [CLOUD], profiles, wildcard) == []  # a typed endpoint-wide price wins


def test_local_endpoint_without_a_price_is_free_cloud_is_unpriced():
    prices.set_for_tests([])
    try:
        def hop(ep):
            return SimpleNamespace(endpoint_name=ep["name"], model="m", endpoint=ep, preset=ep["preset"])
        assert prices.cost_for(hop(LOCAL), 100, 10) == (0.0, 0.0)
        assert prices.cost_for(hop(CLOUD), 100, 10) is None
    finally:
        prices.set_for_tests(None)

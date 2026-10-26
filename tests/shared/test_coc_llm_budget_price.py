"""Unit tests: the CoC budget meter prices a free model as free.

The meter resolves the price of the model it runs on from `ai_prices`. MiniMax M3.1 Flash runs on
the unlimited free plan (owner, 2026-10-23), so its price row is 0. The resolver used to refuse a
price of 0 and the lookup then fell through to another model of the same endpoint, so a CoC Flash
run was charged like claude-haiku-5-5 (~0.025 USD a run) - enough for the daily allowance to
refuse the day's free runs.

No DB: the price rows are passed in.
Repo root is 2 levels up from tests/shared/ (same bootstrap as the other unit tests here).
"""
import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from shared.src.lib.game.clashofclans import llm_budget


def _row(endpoint, model, price_in, price_out, valid_from="2026-10-01T00:00:00+00:00"):
    return {
        "endpoint": endpoint,
        "model": model,
        "price_in": price_in,
        "price_out": price_out,
        "price_cache_read": None,
        "price_cache_write": None,
        "valid_from": valid_from,
    }


FLASH = "MiniMax-M3.1-Flash-Preview"
HAIKU = "claude-haiku-5-5"
ROWS = [
    _row("anthropic", HAIKU, 0.10, 0.50),
    _row("anthropic", FLASH, 0.0, 0.0),
    _row("minimax", FLASH, 0.0, 0.0),
]


def test_a_free_model_keeps_its_zero_price():
    price = llm_budget.resolve_price(FLASH, rows=ROWS)
    assert price["price_in"] == 0
    assert price["price_out"] == 0


def test_a_free_run_costs_nothing():
    price = llm_budget.resolve_price(FLASH, rows=ROWS)
    assert llm_budget.cost_usd(price, 3000, 200) == 0
    # a whole 60-step run
    assert llm_budget.cost_usd(price, 3000, 200) * 60 == 0


def test_a_paid_model_is_still_priced():
    price = llm_budget.resolve_price(HAIKU, rows=ROWS)
    assert price["price_in"] == 0.10
    assert llm_budget.cost_usd(price, 3000, 200) > 0


def test_a_model_without_a_price_row_is_refused():
    import pytest

    with pytest.raises(llm_budget.PriceMissing):
        llm_budget.resolve_price("no-such-model", rows=ROWS)


def test_a_negative_price_is_refused():
    import pytest

    rows = ROWS + [_row("anthropic", "broken-model", -1.0, 0.5)]
    with pytest.raises(llm_budget.PriceMissing):
        llm_budget.resolve_price("broken-model", rows=rows)

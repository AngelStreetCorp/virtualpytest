"""TASK-164: the free Flash lane must survive what the provider does to it.

Two failures made the games stop (2026-10-23):
  * a rate limit (HTTP 429) on the free model ended the run at its first step,
  * the lease of a run was released while the run was still playing, so a second game landed on the same host.

The tests below pin the behaviour that fixes them:
  * a rate-limited FREE model is retried (nothing was billed, so waiting costs nothing),
  * a rate-limited metered model is not retried (its caller falls back instead),
  * a rate-limited step is skipped, the run goes on,
  * the lease is asked for with a TTL the registry grants and renewed long before it ends,
  * the lease holder is a name no ended session can claim.

Run: pytest tests/shared/test_flash_lane_resilience.py -v
"""
import importlib.util
import json
import os

import pytest

from shared.src.lib.ai import prices as P
from shared.src.lib.game.clashofclans import llm_budget as lb
from shared.src.lib.game.clashofclans import llm_player as lp

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "pokemon_dispatch", os.path.join(_here, "..", "..", "scripts", "agent", "pokemon_dispatch.py"))
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

_spec_gd = importlib.util.spec_from_file_location(
    "game_dispatch", os.path.join(_here, "..", "..", "scripts", "agent", "game_dispatch.py"))
GD = importlib.util.module_from_spec(_spec_gd)
_spec_gd.loader.exec_module(GD)

NOW = 1792747000.0
PRICES = [{"endpoint": "anthropic", "model": "claude-haiku-5-5", "price_in": 0.10, "price_out": 0.50,
           "valid_from": "2026-01-01T00:00:00+00:00"}]


class Hop:
    """The little the price helpers need from a hop: an endpoint row, a model, a price."""

    def __init__(self, endpoint, model, endpoint_row=None):
        self.endpoint = endpoint_row or {"name": endpoint, "preset": "anthropic"}
        self.endpoint_name = endpoint
        self.model = model


# --- the price of a hop: free means free ---------------------------------------------------------------

def test_a_flat_plan_is_free():
    # the MiniMax coding plan (the Flash model): the preset is a flat subscription, so a call costs nothing
    assert P.is_free(Hop("minimax", "MiniMax-M3.1-Flash-Preview",
                         {"name": "minimax", "preset": "minimax"})) is True


def test_a_zero_price_row_is_free(monkeypatch):
    monkeypatch.setattr(P, "set_for_tests", P.set_for_tests)   # keep the API symmetric
    P.set_for_tests([{"endpoint": "minimax", "model": "MiniMax-M3.1-Flash-Preview", "price_in": 0, "price_out": 0,
                       "valid_from": "2026-01-01T00:00:00+00:00"}],
                     [{"name": "minimax", "preset": "minimax"}])
    try:
        assert P.is_free(Hop("minimax", "MiniMax-M3.1-Flash-Preview",
                             {"name": "minimax", "preset": "minimax"})) is True
    finally:
        P.set_for_tests(None)


def test_a_metered_model_is_not_free(monkeypatch):
    P.set_for_tests([{"endpoint": "anthropic", "model": "claude-haiku-5-5", "price_in": 0.10, "price_out": 0.50,
                       "valid_from": "2026-01-01T00:00:00+00:00"}],
                     [{"name": "anthropic", "preset": "anthropic"}])
    try:
        assert P.is_free(Hop("anthropic", "claude-haiku-5-5",
                             {"name": "anthropic", "preset": "anthropic"})) is False
    finally:
        P.set_for_tests(None)


# --- the run: a throttled step is skipped, the run goes on -----------------------------------------------

class FakeDev(lp.Device):
    def shot(self, i):
        return "b64", f"/tmp/{i}.jpg"

    def tap(self, x, y):
        return True

    def swipe(self, *a):
        return True


def test_a_rate_limited_step_is_skipped_and_the_run_goes_on(tmp_path):
    b = lb.start_run("t1", "r", "claude-haiku-5-5", 50, 0.05, price_rows=PRICES, path=str(tmp_path / "l"))
    meter = lb.RunMeter(b, 400)
    steps = []
    replies = iter([RuntimeError("minimax (minimax) HTTP 429 for model 'MiniMax-M3.1-Flash-Preview': slow down"),
                     json.dumps({"thought": "t", "action": "tap", "x": 100, "y": 50})] + ["stop"] * 4)

    def ask(system, b64, text):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply, 2000, 200

    res = lp.play(FakeDev(), ask, meter, "play", 5, steps.append, sleep=lambda s: None)
    assert res["stop"] != "api_error"          # the run did not end on the throttle
    assert any("rate limited" in (s.get("note") or "") for s in steps)
    assert any(s.get("action") == "tap" for s in steps)   # and it played after the throttle


def test_another_api_error_still_ends_the_run(tmp_path):
    b = lb.start_run("t1", "r", "claude-haiku-5-5", 50, 0.05, price_rows=PRICES, path=str(tmp_path / "l"))
    meter = lb.RunMeter(b, 400)

    def ask(system, b64, text):
        raise RuntimeError("anthropic (anthropic) HTTP 500: internal error")

    res = lp.play(FakeDev(), ask, meter, "play", 5, lambda s: None, sleep=lambda s: None)
    assert res["stop"] == "api_error"


# --- the lease: a TTL the registry grants, renewed long before it ends -------------------------------------

def test_the_lease_is_asked_for_with_a_ttl_the_registry_grants():
    # the registry caps a low-priority lease at 10 min per claim: asking for more is a wish, not a lease
    assert D.LEASE_TTL_MIN <= 10
    assert GD.LEASE_TTL_MIN <= 10


def test_the_lease_is_renewed_long_before_it_ends():
    # a 10 min lease renewed every 10 min dies exactly at the renewal: the renew must come much earlier
    for module in (D, GD):
        assert module.LEASE_RENEW_S < module.LEASE_TTL_MIN * 60 / 2


def test_the_lease_holder_is_not_a_session_that_can_end():
    # the lease watcher releases the lease of a holder whose session ENDED (a session that existed and is gone).
    # A background service must use a name no session ever had, or its lease is released mid-run.
    for agent in (D.AGENT, "codebox:game-dispatch-coc-flash"):
        assert not agent.lower().startswith("codebox:t"), f"{agent} names a task session: it can be released"
    assert D.AGENT == "codebox:pokemon-dispatch"


# --- the second save: the parallel lane -------------------------------------------------------------------

def test_a_second_save_starts_a_new_game(tmp_path):
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / D.ROM).write_bytes(b"rom")
    assert D.is_new_save(str(canon)) is True
    assert D.push_names(str(canon), False) == [D.ROM]


def test_an_existing_save_is_pushed_with_its_state(tmp_path):
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / D.ROM).write_bytes(b"rom")
    (canon / f"state_{D.SAVE}.json").write_text("{}")
    (canon / f"memory_{D.SAVE}.json").write_text("{}")
    assert D.is_new_save(str(canon)) is False
    assert D.push_names(str(canon), False) == [D.ROM, f"state_{D.SAVE}.json", f"memory_{D.SAVE}.json"]


# --- the daily record: a day is a day ----------------------------------------------------------------------

def test_the_daily_summary_covers_whole_days_not_the_sliding_window(monkeypatch, tmp_path):
    """The per-run table is a sliding window, but the daily summary must not be: with the 24 h window
    the oldest day lost its first runs as the window slid, so a finished day changed after it was written."""
    spec = importlib.util.spec_from_file_location(
        "flash_run_log", os.path.join(_here, "..", "..", "scripts", "agent", "flash_run_log.py"))
    FRL = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(FRL)

    calls = []

    def fake_fetch(hours):
        calls.append(hours)
        return []

    monkeypatch.setattr(FRL, "fetch_runs", fake_fetch)
    doc = tmp_path / "doc.md"
    doc.write_text("x\n<!-- flash-runs:start -->\nold\n<!-- flash-runs:end -->\n"
                   "<!-- flash-daily:start -->\nold\n<!-- flash-daily:end -->\n")
    FRL.write_doc([], str(doc), daily_hours=168)
    assert calls == [168], "the daily summary must be read over its own (wider) window"
    assert "old" not in doc.read_text(), "both blocks are rewritten"

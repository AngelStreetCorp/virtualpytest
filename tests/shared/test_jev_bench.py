"""Offline tests for the Jev benchmark runner (B1 2048, B2 Tetris). No network."""

import json
import random

from scripts.jev_bench import run as run_mod
from scripts.jev_bench.b1_2048 import build_options as b1_options, run_game as b1_game
from scripts.jev_bench.b2_tetris import build_options as b2_options, parse_option, run_game as b2_game
from scripts.jev_bench.common import ARMS, CostGuard, make_decide
from shared.src.lib.game.tetris.board import best_placement, court_rows, empty_court
from shared.src.lib.game2048.board import legal_moves, merge_gain


def _baseline(arm="baseline"):
    return make_decide(arm, "team", CostGuard(100.0))


def test_b1_options_are_the_legal_moves_with_merge_gain():
    rows = [[2, 2, 4, 4]] + [[0] * 4 for _ in range(3)]
    payload = b1_options(rows, 0)
    assert sorted(o["id"] for o in payload["options"]) == sorted(legal_moves(rows))
    for opt in payload["options"]:
        assert f"+{merge_gain(rows, opt['id'])} points" in opt["facts"]
        assert "empty cells after" in opt["facts"] and "board after:" in opt["facts"]
    assert "score" in payload["state"]


def test_b1_baseline_game_is_deterministic():
    a = b1_game(0, 200, _baseline(), lambda *_: None)
    b = b1_game(0, 200, _baseline(), lambda *_: None)
    assert a == b and a["score"] > 0 and a["moves"] > 0 and a["invalid"] == 0


def test_b2_options_top_8_hold_the_best_and_are_deterministic():
    court = empty_court()
    p1 = b2_options(court, "yellow", 0, 4, 0, random.Random("0:0"))
    p2 = b2_options(court, "yellow", 0, 4, 0, random.Random("0:0"))
    assert p1 == p2 and 0 < len(p1["options"]) <= 8
    best = best_placement(court, "yellow", 0, 4, 0)
    assert any((o["d"], o["x"]) == (best["d"], best["x"]) for o in p1["options"])
    for o in p1["options"]:
        assert "rotation" in o["facts"] and "landing height" in o["facts"]
    assert p1["state"] == {"piece": "O", "court": court_rows(court)}


def test_b2_baseline_game_is_deterministic():
    a = b2_game(7, 30, _baseline(), lambda *_: None)
    assert a == b2_game(7, 30, _baseline(), lambda *_: None)
    assert a["pieces"] == 30


def test_b2_piece_sequence_does_not_depend_on_the_arm():
    def pieces(decide):
        seen = []
        b2_game(5, 25, decide, lambda _s, ctx, _r: seen.append(ctx["payload"]["state"]["piece"]))
        return seen

    def worst(ctx):  # different choices -> different boards -> different option counts
        return {**ARMS["baseline"](ctx), "choice": ctx["legal"][-1]}

    assert pieces(_baseline()) == pieces(worst)


def test_illegal_ai_answer_is_invalid_and_the_baseline_move_is_played():
    stub = lambda ctx: {"choice": "NOPE", "confidence": None, "cost": 0.0, "ms": 0, "tokens_in": 0,
                        "tokens_out": 0, "error": "stub"}
    for game in (lambda d, cb: b1_game(0, 40, d, cb), lambda d, cb: b2_game(3, 20, d, cb)):
        seen = []
        out = game(stub, lambda _s, _c, rec: seen.append(rec))
        assert seen and all(r["valid"] is False and r["played"] == r["baseline_choice"] for r in seen)
        assert out["invalid"] == len(seen)


def test_parse_option():
    assert parse_option('x {"reasoning": "r", "option": "p3"} y') == "p3"
    assert parse_option("no json") is None


def test_cost_guard_aborts_after_the_limit(tmp_path):
    guard = CostGuard(2.5)
    guard.record("llm", 2.0)
    assert not guard.over("llm")
    guard.record("llm", 1.0)
    assert guard.over("llm") and not guard.over("jev")

    calls = []

    def stub(_ctx):
        calls.append(1)
        return {"choice": None, "confidence": None, "cost": 1.0, "ms": 5, "tokens_in": 0, "tokens_out": 0,
                "error": ""}

    ARMS["llm"], original = stub, ARMS["llm"]
    try:
        assert run_mod.main(["--bench", "b1", "--arms", "llm", "--seeds", "3", "--max-moves", "10",
                             "--max-cost", "2.5", "--workers", "1", "--out", str(tmp_path)]) == 0
    finally:
        ARMS["llm"] = original
    assert len(calls) == 3
    games = [json.loads(line) for line in (tmp_path / "b1_games.jsonl").read_text().splitlines()]
    assert all(g["aborted"] for g in games) and len(games) == 3
    assert len((tmp_path / "b1_llm.jsonl").read_text().splitlines()) == 3

"""B1 (2048): options with facts per legal move, and the seeded game loop."""

from __future__ import annotations

import random
from typing import Any, Dict

from shared.src.lib.game2048.board import (
    Board, apply_move, board_text, empty_cells, legal_moves, max_tile, merge_gain,
)
from shared.src.lib.game2048.player import LLM_SYSTEM, build_llm_prompt, heuristic_decision, parse_llm_move

from .common import Decide, Record

CORNERS = ((0, 0), (0, 3), (3, 0), (3, 3))
INSTRUCTIONS = "Which move keeps the game going longest and scores most? Keep the biggest tile in a corner."


def build_options(rows: Board, score: int) -> Dict[str, Any]:
    """The decision payload: one option per legal move, with facts."""
    options = []
    for move in legal_moves(rows):
        after = apply_move(rows, move)
        top = max_tile(after)
        corner = "in a corner" if any(after[r][c] == top for r, c in CORNERS) else "not in a corner"
        board = " / ".join(" ".join(str(v or ".") for v in row) for row in after)
        options.append({"id": move, "facts": f"+{merge_gain(rows, move)} points, {empty_cells(after)} empty "
                                             f"cells after, max tile {top} {corner} after; board after: {board}"})
    return {"instructions": INSTRUCTIONS, "state": {"board": board_text(rows), "score": score},
            "options": options}


def _spawn(rng: random.Random, rows: Board) -> None:
    r, c = rng.choice([(r, c) for r in range(4) for c in range(4) if not rows[r][c]])
    rows[r][c] = 2 if rng.random() < 0.9 else 4


def run_game(seed: int, max_moves: int, decide: Decide, on_decision) -> Record:
    """Play one game. ``on_decision(step, ctx, record)`` is called per decision (not for aborts)."""
    rng = random.Random(seed)
    rows: Board = [[0] * 4 for _ in range(4)]
    _spawn(rng, rows)
    _spawn(rng, rows)
    score = moves = invalid = 0
    cost, aborted = 0.0, False
    for step in range(max_moves):
        baseline = heuristic_decision(rows)["move"]
        if baseline is None:
            break
        payload = build_options(rows, score)
        legal = [o["id"] for o in payload["options"]]
        ctx = {"payload": payload, "legal": legal, "baseline_choice": baseline, "system": LLM_SYSTEM,
               "prompt": build_llm_prompt(rows, score, legal),
               "parser": lambda text, legal=legal: parse_llm_move(text, legal)[0]}
        record = decide(ctx)
        if record.get("aborted"):
            aborted = True
            break
        valid = record.get("choice") in legal
        played = record["choice"] if valid else baseline
        record.update(valid=valid, played=played, baseline_choice=baseline)
        on_decision(step, ctx, record)
        invalid += not valid
        cost += record.get("cost") or 0.0
        score += merge_gain(rows, played)
        rows = apply_move(rows, played)
        _spawn(rng, rows)
        moves += 1
    return {"score": score, "max_tile": max_tile(rows), "moves": moves, "invalid": invalid, "cost": cost,
            "aborted": aborted}

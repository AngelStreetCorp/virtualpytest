"""B2 (Tetris): top-8 El-Tetris placements as options with facts, and the seeded game loop.

The game RNG only spawns pieces, so every arm sees the same piece sequence. The option order is
shuffled with a separate RNG seeded from (seed, step).
"""

from __future__ import annotations

import json
import random
from typing import Any, Dict, List, Optional

from shared.src.lib.game.tetris.board import (
    NX, NY, PIECE_NAMES, SHAPES, WEIGHTS, Court, best_placement, court_rows, features, fits,
    landing_y, place, reachable,
)

from .common import Decide, Record

TOP_K = 8
INSTRUCTIONS = "Which placement keeps the stack low and clean and clears rows?"


def _placements(court: Court, piece: str, d0: int, x0: int, y0: int) -> List[Dict[str, Any]]:
    """Every reachable placement, enumerated like ``best_placement``, with its El-Tetris score."""
    found = []
    for d in range(4):
        for x in range(-3, NX):
            if not reachable(court, piece, d0, x0, y0, d, x):
                continue
            y = landing_y(court, piece, d, x, y0)
            if y is None:
                continue
            after, placed, lines = place(court, piece, d, x, y)
            feats = features(after, placed, lines)
            found.append({"d": d, "x": x, "y": y, "lines": lines, "feats": feats,
                          "score": sum(w * f for w, f in zip(WEIGHTS, feats))})
    return found


def build_options(court: Court, piece: str, d0: int, x0: int, y0: int, shuffle_rng: random.Random
                  ) -> Dict[str, Any]:
    """The decision payload: top-8 placements by El-Tetris score, shuffled, facts without the score."""
    top = sorted(_placements(court, piece, d0, x0, y0), key=lambda p: p["score"], reverse=True)[:TOP_K]
    shuffle_rng.shuffle(top)
    options = []
    for i, p in enumerate(top, start=1):
        landing, _lines, row_t, col_t, holes, wells = p["feats"]
        options.append({
            "id": f"p{i}", "d": p["d"], "x": p["x"], "y": p["y"],
            "facts": f"rotation {p['d']}, column {p['x']}: clears {p['lines']} rows, landing height "
                     f"{landing:g}, {holes:g} holes, {row_t:g} row transitions, {col_t:g} column "
                     f"transitions, wells {wells:g}"})
    return {"instructions": INSTRUCTIONS, "state": {"piece": PIECE_NAMES[piece], "court": court_rows(court)},
            "options": options}


def build_prompt(payload: Dict[str, Any]) -> str:
    lines = ["Court (top row first, # filled, . empty):", *payload["state"]["court"],
             f"Incoming piece: {payload['state']['piece']}", "", "Options (id: facts):"]
    lines += [f"{o['id']}: {o['facts']}" for o in payload["options"]]
    lines += ["", f"{INSTRUCTIONS} Answer as JSON: "
                  '{"reasoning": "<at most 15 words>", "option": "<option id>"}']
    return "\n".join(lines)


def parse_option(text: str) -> Optional[str]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        option = json.loads(text[start:end + 1]).get("option")
    except (ValueError, AttributeError):
        return None
    return str(option).strip() if option else None


def run_game(seed: int, max_pieces: int, decide: Decide, on_decision) -> Record:
    """Play one game. Game over when a spawn doesn't fit."""
    rng = random.Random(seed)
    court: Court = [[0] * NY for _ in range(NX)]
    rows = pieces = invalid = 0
    cost, aborted = 0.0, False
    for step in range(max_pieces):
        piece = rng.choice(list(SHAPES))
        x0, y0, d0 = rng.randint(0, NX - 4), 0, 0
        if not fits(court, piece, d0, x0, y0):
            break
        payload = build_options(court, piece, d0, x0, y0, random.Random(f"{seed}:{step}"))
        options = {o["id"]: o for o in payload["options"]}
        best = best_placement(court, piece, d0, x0, y0)
        if best is None:
            break
        baseline = next(i for i, o in options.items() if (o["d"], o["x"]) == (best["d"], best["x"]))
        ctx = {"payload": payload, "legal": list(options), "baseline_choice": baseline, "system": "",
               "prompt": build_prompt(payload), "parser": parse_option}
        record = decide(ctx)
        if record.get("aborted"):
            aborted = True
            break
        valid = record.get("choice") in options
        played = record["choice"] if valid else baseline
        record.update(valid=valid, played=played, baseline_choice=baseline)
        on_decision(step, ctx, record)
        invalid += not valid
        cost += record.get("cost") or 0.0
        o = options[played]
        court, _placed, cleared = place(court, piece, o["d"], o["x"], o["y"])
        rows += cleared
        pieces += 1
    return {"rows": rows, "pieces": pieces, "invalid": invalid, "cost": cost,
            "aborted": aborted}

"""
Move players for 2048.

heuristic: fixed priority LEFT > DOWN > RIGHT > UP (bottom-left corner strategy), no model.
llm:       one AI-gateway call per move (usage text.game_2048); falls back to the heuristic
           when the call fails or the answer holds no legal move.
"""

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from .board import MOVES, Board, apply_move, board_text, first_legal, legal_moves, merge_gain

LLM_USAGE = "text.game_2048"
LLM_MAX_TOKENS = 300
# Consecutive failed LLM calls before the rest of the game falls back to the heuristic,
# so an offline model never turns every move into a timeout.
LLM_MAX_CONSECUTIVE_ERRORS = 3
LLM_SYSTEM = "You are playing the game 2048 on a 4x4 board. Reply with one JSON object only, no other text."
LLM_TIPS = (
    "Tips: keep the biggest tile in the bottom-left corner, keep the bottom row full and ordered, "
    "prefer LEFT and DOWN, use RIGHT only when needed and UP only as a last resort. "
    "Merges and empty cells both matter."
)

Decision = Dict[str, Any]
Decider = Callable[[Board, int], Decision]


def heuristic_decision(rows: Board) -> Decision:
    move = first_legal(rows)
    if move is None:
        return {"move": None, "decided_by": "heuristic", "reasoning": "no legal move"}
    blocked = list(MOVES[:MOVES.index(move)])
    reasoning = f"{' / '.join(blocked)} blocked -> {move}" if blocked else f"{move} is first in {'>'.join(MOVES)}"
    return {"move": move, "decided_by": "heuristic", "reasoning": reasoning}


def heuristic_decide(rows: Board, score: int) -> Decision:
    return heuristic_decision(rows)


def build_llm_prompt(rows: Board, score: int, legal: List[str]) -> str:
    lines = [
        "Board (row 1 is the top, . is empty):",
        board_text(rows),
        f"Score: {score}",
        "",
        "Legal moves, with the board right after each move (before the new random tile appears):",
    ]
    for move in legal:
        after = apply_move(rows, move)
        empty = sum(1 for r in after for v in r if not v)
        lines.append(f"{move}: +{merge_gain(rows, move)} points, {empty} empty cells")
        lines.append(board_text(after))
    lines += [
        "",
        LLM_TIPS,
        "",
        'Answer as JSON: {"reasoning": "<at most 15 words>", "move": "<' + "|".join(legal) + '>"}',
    ]
    return "\n".join(lines)


def parse_llm_move(text: str, legal: List[str]) -> tuple:
    """(move, reasoning) from the model answer; move is None when absent or illegal."""
    reasoning, move = "", None
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            reasoning = str(obj.get("reasoning") or "").strip()
            move = str(obj.get("move") or "").strip().upper()
        except (ValueError, AttributeError):
            pass
    if not move:
        found = re.search(r'"move"\s*:\s*"(\w+)"', text)
        move = found.group(1).upper() if found else None
    return (move if move in legal else None), reasoning


def make_llm_decider(team_id: Optional[str]) -> Decider:
    """Per-move decision through the AI gateway (blocking call)."""
    from shared.src.lib.ai import gateway

    state = {"errors": 0, "disabled": ""}

    def decide(rows: Board, score: int) -> Decision:
        fallback = heuristic_decision(rows)
        if fallback["move"] is None:
            return fallback
        if state["disabled"]:
            return {**fallback, "decided_by": "heuristic_fallback", "error": state["disabled"]}
        legal = legal_moves(rows)
        started = time.time()
        result = gateway.complete(
            LLM_USAGE, build_llm_prompt(rows, score, legal),
            system=LLM_SYSTEM, max_tokens=LLM_MAX_TOKENS, temperature=0.0, team_id=team_id,
        )
        usage = result.get("usage") or {}
        call = {
            "llm_called": True,
            "legal": legal,
            "model": result.get("model") or "",
            "profile": result.get("profile") or "",
            "endpoint": result.get("endpoint") or "",
            "tokens_in": int(usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("completion_tokens") or 0),
            "llm_ms": int((time.time() - started) * 1000),
        }
        if not result.get("success"):
            state["errors"] += 1
            error = result.get("error") or "LLM call failed"
            if state["errors"] >= LLM_MAX_CONSECUTIVE_ERRORS:
                state["disabled"] = f"LLM disabled after {state['errors']} failed calls: {error}"
            return {**fallback, **call, "decided_by": "heuristic_fallback", "error": error}
        state["errors"] = 0
        content = result.get("content") or ""
        move, reasoning = parse_llm_move(content, legal)
        if move is None:
            return {**fallback, **call, "decided_by": "heuristic_fallback",
                    "error": "no legal move in the answer", "raw_answer": content[:500]}
        return {"move": move, "decided_by": "llm", "reasoning": reasoning, **call, "raw_answer": content[:500]}

    return decide

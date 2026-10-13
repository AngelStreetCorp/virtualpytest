"""
The strategist: the long-term plan, lessons learned and the rules the runner follows.

Called on events that should change the plan (a defeat, a new milestone). An LLM writes:
  {"plan": "...", "lessons": ["..."], "train_to_level": 13 | null, "reason": "..."}
The plan and lessons are the readable strategy diary; `train_to_level` is a rule the runner applies
(grind before the next milestone's goal). The memory holds the plan, the lessons (deduplicated, at
most MAX_LESSONS) and a short journal, so the context stays bounded however long the game runs.
Without an LLM, `fallback` keeps the game going: after a defeat, train two levels above the party.
"""

import json
import re
from typing import Callable, Dict, List, Optional

MAX_LESSONS = 12
MAX_JOURNAL = 30

SYSTEM = ("You are the strategist of an AI playing Pokémon Blue (French version). A harness moves, fights "
          "turn by turn and follows the story; you set the long-term plan. Reply with one JSON object only.")


def memory(memo: Dict) -> Dict:
    return memo.setdefault("strategy", {"plan": "", "lessons": [], "journal": [], "rules": {}})


def journal(memo: Dict, line: str) -> None:
    j = memory(memo)["journal"]
    j.append(line)
    del j[:-MAX_JOURNAL]


def prompt(trigger: str, snapshot: Dict, memo: Dict) -> str:
    mem = memory(memo)
    return "\n".join([
        f"Event: {trigger}.",
        f"Current milestone: {snapshot['milestone']} — {snapshot['goal']}.",
        "Milestones already done: " + (", ".join(snapshot.get("done") or []) or "(none)") + ".",
        f"Party: {json.dumps(snapshot['party'], ensure_ascii=False)}",
        "Moves already known: " + "; ".join(
            f"{p['name']}: " + ", ".join(m.split(" (")[0] for m in p.get("moves", [])) for p in snapshot["party"]) + ".",
        f"Money: {snapshot['money']}. Badges: {snapshot['badges']}.",
        "Levels of the last opponents met: " + (", ".join(map(str, snapshot.get("opponent_levels") or [])) or "(none yet)") + ".",
        f"Previous plan (may be outdated — check every step against the facts above): {mem['plan'] or '(none yet)'}",
        "Lessons so far: " + ("; ".join(mem["lessons"]) or "(none)"),
        "Recent journal: " + (" | ".join(mem["journal"][-10:]) or "(empty)"),
        "",
        "Gen 1 facts you may use: type effectiveness matters most (e.g. Grass and Water beat Rock/Ground; "
        "Normal moves are weak on Rock). Beating Pokémon far below your level gives almost no experience, "
        "so training on them is very slow.",
        "Revise the plan for the CURRENT milestone: drop steps that are already achieved (see the milestones done "
        "and the party's level and moves). Never plan to learn a move the party already knows.",
        "Answer: {\"plan\": short plan for the next steps, \"lessons\": [new lessons only], "
        "\"train_to_level\": the level the party leader should reach before the milestone's goal, only when the "
        "party is too weak for the coming fights (e.g. after a defeat), else null; \"reason\": one sentence}.",
    ])


def parse(text: str) -> Optional[Dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


ATTRITION_LEVELS = 15   # a defeat against opponents this many levels below the leader is lost PP and HP, not weakness


def fallback(trigger: str, snapshot: Dict) -> Dict:
    top = max((p["level"] for p in snapshot["party"]), default=1)
    opponents = snapshot.get("opponent_levels") or []
    if trigger.startswith("defeat") and opponents and top - max(opponents) >= ATTRITION_LEVELS:
        return {"plan": f"Lost at {snapshot['milestone']} to a string of weak trainers: heal more often, no training.",
                "lessons": [f"Lost at {snapshot['milestone']} to opponents at level {max(opponents)} with the leader at {top}: "
                            "the party ran out of PP, training does not help."],
                "train_to_level": None, "reason": "fallback rule after a defeat by attrition"}
    if trigger.startswith("defeat"):
        return {"plan": f"Lost at {snapshot['milestone']}: train before trying again.",
                "lessons": [f"Lost at {snapshot['milestone']} with the party at level {top}."],
                "train_to_level": top + 2, "reason": "fallback rule after a defeat"}
    return {"plan": f"Follow the story: {snapshot['goal']}.", "lessons": [], "train_to_level": None,
            "reason": "fallback rule"}


def update(memo: Dict, trigger: str, snapshot: Dict, complete: Optional[Callable] = None) -> Dict:
    """Ask the strategist (an LLM through `complete(prompt, system)`, returning the answer text or
    {content, usage, cost, model, ms}) or the fallback; apply the answer to the memory. Returns the
    decision with its source and the call (prompt, raw answer, usage) for the game report."""
    decision, source, call = None, "fallback", {}
    if complete:
        text = prompt(trigger, snapshot, memo)
        out = complete(text, SYSTEM)
        # `complete` returns the answer text, or {content, usage, cost, model, ms}
        call = out if isinstance(out, dict) else {"content": out}
        call["prompt"] = text
        decision = parse(call.get("content") or "")
        source = "llm"
    if not decision:
        decision, source = fallback(trigger, snapshot), "fallback"
    mem = memory(memo)
    if decision.get("plan"):
        mem["plan"] = str(decision["plan"])[:400]
    for lesson in decision.get("lessons") or []:
        lesson = str(lesson)[:200]
        if lesson and lesson not in mem["lessons"]:
            mem["lessons"].append(lesson)
    del mem["lessons"][:-MAX_LESSONS]
    level = decision.get("train_to_level")
    mem["rules"]["train_to_level"] = int(level) if isinstance(level, (int, float)) and level else None
    journal(memo, f"{trigger}: {decision.get('reason', '')}"[:200])
    return {**decision, "source": source, "call": call}

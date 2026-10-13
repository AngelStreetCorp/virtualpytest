"""
Durable log of the router turn's skill pick (TASK-47).

In router mode the agent either loads a skill (``LOAD SKILL [name]``, or an automatic
trigger match) or answers directly, with or without direct tools. That pick was never
stored, so nobody could measure whether a cheap decision model could do the routing.

One ``ai_decisions`` row per routing turn (usage ``agent.<name>.route``), written when the
turn ends so it already carries what happened next:

    state     {"message": <first 500 chars>, "available_skills": [...], "mode": "router"}
    questions {"skill": {"type": "choice", "options": [... , "answered_directly"]}}
    answers   {"skill": {"type": "choice", "choice": <skill | answered_directly>,
                         "confidence": null, "probabilities": {}}}
    ok/error  False when the turn raised an error event
    model     the routed model of the router turn, ``profile`` its profile
    refs      {session_id, decided_by: llm | trigger_rule, skill, load_ok, tools: [...]}
    outcome   {skill, success, errors, tool_calls}   (success = no error event in the turn)

``ms`` is the whole turn, not the routing call alone. Only root turns that START in
router mode are logged: a turn with a skill already loaded (earlier turn, or preloaded by
the test-prompt feature) is not a routing decision, and delegated continuations are skipped.
Rows need a team (``team_id`` is NOT NULL and every read filters by it); without one nothing
is written. The write runs on a background thread and never raises.
"""

import threading
import time
from typing import Any, Dict, List, Optional

from .message_types import AgentEvent, EventType

ANSWERED_DIRECTLY = "answered_directly"
MESSAGE_MAX_CHARS = 500
ROUTE_LOG_RETENTION_DAYS = 30
# Module-level: prune each team's 'agent.atlas.route' rows at most once per hour per process.
_PRUNE_INTERVAL_SECONDS = 3600
_LAST_PRUNE_AT: Dict[str, float] = {}


def route_usage_key(agent_usage: str) -> str:
    """``agent.atlas`` -> ``agent.atlas.route`` (never the skill-suffixed key)."""
    return f"{agent_usage}.route"


class RoutingTracker:
    """Watches one router-mode turn's events and writes the decision row when it ends."""

    def __init__(self, *, team_id: Optional[str], session_id: Optional[str], agent_usage: str, message: str,
                 available_skills: List[str], model: Optional[str], profile: Optional[str]):
        self.team_id = team_id
        self.session_id = session_id
        self.usage_key = route_usage_key(agent_usage)
        self.message = (message or "")[:MESSAGE_MAX_CHARS]
        self.available_skills = list(available_skills or [])
        self.model = model
        self.profile = profile
        self.started = time.time()
        self.picked: Optional[str] = None      # skill named by the model
        self.load_failed = False
        self.errors: List[str] = []
        self.tools: List[str] = []

    def observe(self, event: AgentEvent) -> None:
        if event.type == EventType.SKILL_LOADED and self.picked is None:
            self.picked = str(event.content or "").strip()
        elif event.type == EventType.ERROR:
            err = str(event.error or event.content or "error")
            self.errors.append(err[:300])
            if err.startswith("skill_not_available"):
                self.load_failed = True
        elif event.type == EventType.TOOL_CALL and event.tool_name:
            self.tools.append(event.tool_name)

    def build_row(self, active_skill: Optional[str], aborted: bool = False) -> Dict[str, Any]:
        """The ``ai_decisions`` row. ``active_skill``: the skill loaded when the turn ended."""
        if self.picked:
            decided_by, choice = "llm", self.picked
            load_ok = not self.load_failed
        elif active_skill:
            decided_by, choice, load_ok = "trigger_rule", active_skill, True
        else:
            decided_by, choice, load_ok = "none", ANSWERED_DIRECTLY, True
        success = not self.errors and not aborted
        error = "aborted" if aborted and not self.errors else ("; ".join(self.errors)[:500] or None)
        return {
            "team_id": self.team_id,
            "usage_key": self.usage_key,
            "request_id": self.session_id,
            "profile": self.profile,
            "model": self.model,
            "state": {"message": self.message, "available_skills": self.available_skills, "mode": "router"},
            "questions": {"skill": {"type": "choice", "options": self.available_skills + [ANSWERED_DIRECTLY]}},
            "answers": {"skill": {"type": "choice", "choice": choice, "confidence": None, "probabilities": {}}},
            "ok": success,
            "error": error,
            "ms": int((time.time() - self.started) * 1000),
            "tokens_in": 0,
            "refs": {"session_id": self.session_id, "decided_by": decided_by, "skill": choice,
                     "load_ok": load_ok, "tools": self.tools[:20]},
            "outcome": {"skill": choice, "success": success, "errors": len(self.errors),
                        "tool_calls": len(self.tools)},
            "outcome_at": None,  # set by write() so it is the write time
        }

    def write(self, active_skill: Optional[str], aborted: bool = False) -> None:
        """Insert the row in the background. Never raises."""
        if not self.team_id:
            return
        try:
            row = self.build_row(active_skill, aborted)
        except Exception as e:
            print(f"[AGENT] routing log build failed: {e}")
            return
        threading.Thread(target=_insert, args=(row,), daemon=True).start()


def _insert(row: Dict[str, Any]) -> None:
    try:
        from datetime import datetime, timezone

        from shared.src.lib.database import ai_decisions_db
        row["outcome_at"] = datetime.now(timezone.utc).isoformat()
        decision_id = ai_decisions_db.insert_decision(row)
    except Exception as e:
        print(f"[AGENT] routing log write failed: {e}")
        return
    _emit_decision(decision_id, row)
    _maybe_prune_route_log(row.get("team_id"))


def _emit_decision(decision_id: Optional[str], row: Dict[str, Any]) -> None:
    """Live tail of the Agent Dashboard (TASK-54): the routing decision just written. Never raises."""
    if not decision_id:
        return
    try:
        from agent.activity import rows as activity_rows, service as activity_service
        from agent.activity.sources import agent_for_usage_key, part_for_usage_key
        agent = agent_for_usage_key(row.get("usage_key"))
        part = part_for_usage_key(agent, row.get("usage_key")) or "decision"
        live = activity_rows.build_decision_row({**row, "id": decision_id, "created_at": row.get("outcome_at")},
                                                part, is_admin=False)
        activity_service.emit_activity(agent, row.get("team_id") or "", activity_service.public_row(live))
    except Exception as e:
        print(f"[AGENT] routing log live emit failed: {e}")


def _maybe_prune_route_log(team_id: Optional[str]) -> None:
    """Prune old routing-log entries at most once per hour per team. Never raises."""
    if not team_id:
        return
    now = time.time()
    last = _LAST_PRUNE_AT.get(team_id)
    if last is not None and (now - last) < _PRUNE_INTERVAL_SECONDS:
        return
    _LAST_PRUNE_AT[team_id] = now
    try:
        from shared.src.lib.database import ai_decisions_db
        ai_decisions_db.prune_decisions(team_id, route_usage_key("agent.atlas"),
                                        ROUTE_LOG_RETENTION_DAYS)
    except Exception as e:
        print(f"[AGENT] routing log prune failed: {e}")

"""Atlas quick step (TASK-140 Q1-Q6): pure logic.

At the start of an Atlas turn one small model call may pick ONE quick tool for a short command ("open the heatmap",
"take control of stb1"). The manager (``core/manager.py`` ``_quick_step``) runs the call and the tool; this module
holds everything that can be decided without a model:

- ``POOL``: the tools that may ever be quick; ``BASE``: the ones every user has;
- ``eligible()``: which messages get a quick step at all;
- ``quick_tools()``: the user's quick set, learned from ``atlas_quick_tool_stats`` (uses, misses, demotion);
- schema and named-device checks (BUG-0323 / BUG-0355: a named device is never substituted);
- the system prompt, the escape tool and the response parsing.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Callable, Optional

# Single-call tools whose arguments come from known lists (page, device, node, doc query), read-only or low-risk
# device actions. Nothing here deletes, edits, saves, creates, runs a script / testcase / campaign, or changes
# settings, permissions or deployments (a test enforces the name prefixes).
POOL: dict[str, str] = {
    "show_page": "open an app page beside the chat",
    "navigate_to_page": "open an app page",
    "take_control": "take control of a device",
    "release_control": "release a device",
    "navigate_to_node": "move a device to a navigation node (goto)",
    "capture_screenshot": "screenshot of a device",
    "get_device_info": "info about a device",
    "list_hosts": "list the hosts",
    "search_docs": "search the documentation",
    "search_videos": "search the videos",
    "get_available_pages": "list the app pages",
    "get_execution_results": "recent script results",
    "query_kpi_radar": "KPI radar of a user interface",
    # TASK-175: one-tool reads that took a full model loop (median 11-16 k tokens, 2026-10 audit).
    "list_testcases": "list the test cases",
    "list_scripts": "list the scripts",
    "list_campaigns": "list the campaigns",
    "list_userinterfaces": "list the user interfaces",
    "list_actions": "list the remote keys / actions of a device",
    "dump_ui_elements": "dump the UI elements on a device's screen",
    "get_alerts": "list the open alerts / incidents",
    "get_stream_status": "which device video streams are running, stuck or stopped (tiles on loading)",
}
BASE: tuple[str, ...] = ("show_page", "navigate_to_page", "take_control", "navigate_to_node", "capture_screenshot")

QUICK_CAP = 8
# A message that names what a POOL tool does gets that tool in its quick set this turn, on top of BASE and the
# user's learned tools: a first-time "list my test cases" must not wait for five uses (TASK-175).
HINTS: dict[str, tuple[str, ...]] = {
    "list_testcases": ("test case", "testcase"),
    "list_scripts": ("script",),
    "list_campaigns": ("campaign",),
    "list_userinterfaces": ("user interface", "userinterface"),
    "list_actions": ("remote key", "keys of", "actions can", "what actions", "list the actions"),
    "dump_ui_elements": ("ui element", "dump the ui", "elements on"),
    "get_alerts": ("alert", "incident"),
    "get_stream_status": ("stream", "loading", "tile", "ffmpeg", "not playing"),
    "list_hosts": ("hosts", "online", "offline", "down?"),
    # lock state only: "awake?" is a screen question (a screenshot), not a get_device_info one (live run 2026-10-26)
    "get_device_info": ("free or", "in use", "who is controlling", "status of"),
    "get_execution_results": ("last run", "last script", "did the", "test results", "results for"),
}
MAX_QUESTION_WORDS = 8
_REASONING_OPENERS = frozenset({"why", "how", "pourquoi", "comment", "warum", "wie", "explain"})
MIN_USER_USES = 5            # below this the team's top tools are used instead of the user's own
DEMOTE_MIN_MISSES = 3
DEMOTE_MISS_RATE = 0.3
MAX_WORDS = 12
ESCAPE_TOOL = "ask_atlas"
QUICK_USAGE = "agent.atlas.quick"

_QUESTION_WORDS = {
    "what", "why", "how", "when", "which", "who", "is", "are", "can", "could", "do", "does",
    "quoi", "pourquoi", "comment", "quand", "quel", "quelle", "qui", "est-ce",
    "was", "warum", "wie", "wann", "welche", "wer", "ist", "sind", "kann",
}


def enabled() -> bool:
    return os.getenv("ATLAS_QUICK_STEP", "on").strip().lower() != "off"


def eligible(message: str) -> bool:
    """A short command (at most 12 words), or a short question (at most 8 words) that names a POOL tool's job.

    TASK-175: "is phone slot 1 awake?" / "which devices are online?" are one tool call; they used to take the
    full model loop because any question was refused. A question that hints no tool still goes to the model.
    """
    words = (message or "").split()
    if not words or len(words) > MAX_WORDS:
        return False
    opener = re.sub(r"[^\w-]", "", words[0].lower())
    question = "?" in message or opener in _QUESTION_WORDS
    if not question:
        return True
    # "why" / "how" need reasoning, not one tool: "why did the last run fail?" was answered with list_hosts
    # (TASK-175 bench). "how many" is a count.
    if opener in _REASONING_OPENERS and not message.lower().startswith("how many"):
        return False
    return len(words) <= MAX_QUESTION_WORDS and bool(hinted_tools(message))


def hinted_tools(message: str) -> list[str]:
    """The POOL tools whose job the message names, in POOL order."""
    text = " " + (message or "").lower() + " "
    return [tool for tool in POOL if any(h in text for h in HINTS.get(tool, ()))]


def is_demoted(row: Optional[dict]) -> bool:
    misses = int((row or {}).get("misses") or 0)
    hits = int((row or {}).get("hits") or 0)
    return misses >= DEMOTE_MIN_MISSES and misses / (hits + misses) > DEMOTE_MISS_RATE


def quick_tools(team_id: str, user_id: str, allowed: list[str], *,
                load_user: Optional[Callable[[str, str], dict]] = None,
                load_team: Optional[Callable[[str], dict]] = None, message: str = "") -> list[str]:
    """BASE + the tools the message names (``hinted_tools``) + the user's top POOL tools by uses (the team's when
    the user has < 5 uses), minus demoted, within ``allowed``, at most 8. BASE and hinted tools are kept."""
    if load_user is None or load_team is None:
        from shared.src.lib.database import atlas_quick_stats_db as stats_db
        load_user, load_team = load_user or stats_db.load, load_team or stats_db.load_team
    mine = load_user(team_id, user_id) if user_id else {}
    source = mine if sum(int(r.get("uses") or 0) for r in mine.values()) >= MIN_USER_USES else load_team(team_id)
    allowed_set = set(allowed or [])
    chosen = [t for t in BASE if t in allowed_set]
    chosen += [t for t in hinted_tools(message) if t in allowed_set and t not in chosen]
    ranked = sorted((t for t in POOL if t not in BASE and int((source.get(t) or {}).get("uses") or 0) > 0),
                    key=lambda t: (-int(source[t].get("uses") or 0), t))
    for tool in ranked:
        if len(chosen) >= QUICK_CAP:
            break
        if tool in allowed_set and not is_demoted(mine.get(tool)):
            chosen.append(tool)
    return chosen[:QUICK_CAP]


# ------------------------------------------------------------------ checks

_TYPES = {"string": str, "boolean": bool, "integer": int, "number": (int, float), "object": dict, "array": list}


def validate_args(schema: dict, args: Any) -> Optional[str]:
    """None when ``args`` fit the tool's input schema (required, types, enums), else the reason."""
    if not isinstance(args, dict):
        return "arguments are not an object"
    props = (schema or {}).get("properties") or {}
    for name in (schema or {}).get("required") or []:
        if args.get(name) in (None, ""):
            return f"missing {name}"
    for name, value in args.items():
        spec = props.get(name)
        if spec is None:
            return f"unknown argument {name}"
        want = _TYPES.get(spec.get("type"))
        if want and (not isinstance(value, want) or (spec.get("type") in ("integer", "number") and isinstance(value, bool))):
            return f"{name} has the wrong type"
        if spec.get("enum") and value not in spec["enum"]:
            return f"{name} is not one of the allowed values"
    return None


def check_devices(args: dict, devices: list[dict]) -> Optional[str]:
    """None when any device the arguments name exists exactly once in the session's list, else the reason.
    Never substitute (BUG-0323 / BUG-0355)."""
    devices = [d for d in (devices or []) if isinstance(d, dict)]
    name = args.get("device_name")
    if isinstance(name, str) and name.strip():
        if sum(1 for d in devices if str(d.get("device_name") or "").strip().lower() == name.strip().lower()) != 1:
            return f"device '{name}' not found exactly once"
    device_id, host = args.get("device_id"), args.get("host_name")
    if device_id:
        matches = [d for d in devices if d.get("device_id") == device_id and (not host or d.get("host_name") == host)]
        if len(matches) != 1:
            return f"device '{device_id}' not found exactly once"
    return None


def missing_device(args: dict, devices: list[dict]) -> Optional[str]:
    """The device name (or id) the arguments name that matches NO device of the session, else None.

    TASK-175: a device that is not there (a typo, another server's device) sent the full model hunting:
    up to 13 calls and 366 k tokens for "list the remote keys of phone slot 1". An ambiguous name
    (several matches) is not "missing" and still goes to the model.
    """
    devices = [d for d in (devices or []) if isinstance(d, dict)]
    if not devices:
        # No list to check against (an API client, or a page that sent none): the device may well exist on
        # another server (TASK-179), so let the model and its owner lookup decide (BUG-0969).
        return None
    name = args.get("device_name") if isinstance(args, dict) else None
    if isinstance(name, str) and name.strip():
        wanted = name.strip().lower()
        if not any(str(d.get("device_name") or "").strip().lower() == wanted for d in devices):
            return name.strip()
        return None
    device_id = args.get("device_id") if isinstance(args, dict) else None
    host = args.get("host_name") if isinstance(args, dict) else None
    if device_id and not any(d.get("device_id") == device_id and (not host or d.get("host_name") == host) for d in devices):
        return f"{host}/{device_id}" if host else str(device_id)
    return None


def missing_device_text(name: str, devices: list[dict]) -> str:
    names = sorted({str(d.get("device_name")) for d in devices or [] if isinstance(d, dict) and d.get("device_name")})
    shown = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
    return f'I can\'t find a device named "{name}" here. Devices I can see: {shown}. Which one do you mean?'


def validate_pick(tool: str, args: Any, quick: list[str], schemas: dict[str, dict], devices: list[dict]) -> Optional[str]:
    """None when a picked tool may run now, else why not (not quick / invalid arguments / device rule)."""
    if tool not in quick or tool not in schemas:
        return f"{tool} is not in the quick set"
    return validate_args(schemas[tool], args) or check_devices(args, devices)


# Info tools the small model reaches for when no tool fits (TASK-163: "Screenshot <device>" answered with the page list).
# Each needs a word in the message that is about its subject; a message that names a device is about that device.
_INFO_WORDS: dict[str, tuple[str, ...]] = {
    "get_available_pages": ("page",),
    "search_docs": ("doc", "guide", "manual", "how do", "how to", "how can"),
    "search_videos": ("video", "tutorial"),
    "get_execution_results": ("result", "report", "run", "pass", "fail", "script"),
    "query_kpi_radar": ("kpi", "radar", "quality"),
    "list_hosts": ("host", "device", "online", "connected", "list", "all"),
    # the lock-state words the TASK-175 HINTS route here: get_device_info reports the lock (free / in use / who),
    # not whether the screen is on — "awake?" needs a screenshot and stays with the full turn
    "get_device_info": ("info", "status", "detail", "model", "online", "free", "busy", "in use", "controlling"),
    "take_control": ("control", "lock"),
    "release_control": ("release", "free", "unlock", "done with"),
}
_NAMES_A_DEVICE = {"get_available_pages", "search_docs", "search_videos", "get_execution_results", "query_kpi_radar", "list_hosts"}


_COMMAND_VERBS = {"press", "take", "release", "lock", "free", "wake", "zap", "tune", "switch", "mute", "unmute", "raise",
                  "lower", "turn", "put", "send", "go", "navigate", "screenshot", "channel", "volume", "run", "execute",
                  "launch", "start", "stop", "open", "close", "dump", "show", "capture", "reboot", "power"}


def is_device_command(message: str, devices: list[dict]) -> bool:
    """An imperative that names a known device ("Press HOME on stb3"): an action, never a docs question for the FAQ."""
    words = (message or "").split()
    if not words or re.sub(r"[^\w-]", "", words[0].lower()) not in _COMMAND_VERBS:
        return False
    text = message.lower()
    return any(str(d.get("device_name") or "").strip() and str(d["device_name"]).strip().lower() in text
               for d in devices or [] if isinstance(d, dict))


_PAGE_WORDS = ("page", "open", "heatmap", "dashboard", "report", "show the", "show me the")


def fits(tool: str, message: str, devices: list[dict]) -> bool:
    """False when an info tool was picked for a message that is not about its subject: Atlas then takes the full turn."""
    text = (message or "").lower()
    if tool in ("show_page", "navigate_to_page"):  # a page about one device is for "open/show the page", not "what is X showing"
        named = any(str(d.get("device_name") or "").strip().lower() in text
                    for d in devices or [] if isinstance(d, dict) and str(d.get("device_name") or "").strip())
        return not named or any(w in text for w in _PAGE_WORDS)
    words = _INFO_WORDS.get(tool)
    if not words:
        return True
    if tool in _NAMES_A_DEVICE and any(
            str(d.get("device_name") or "").strip().lower() and str(d.get("device_name")).strip().lower() in text
            for d in devices or [] if isinstance(d, dict)):
        return False
    return any(w in text for w in words)


# ------------------------------------------------------------------ prompt and response

def escape_tool() -> dict:
    return {
        "name": ESCAPE_TOOL,
        "description": "Anything else: questions, several steps, unclear requests, or when unsure.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }


def system_prompt(context: dict) -> str:
    devices = [d for d in (context.get("available_devices") or []) if isinstance(d, dict)]
    listed = "; ".join(f"{d.get('device_name', '?')} (host_name='{d.get('host_name', '')}', device_id='{d.get('device_id', '')}')"
                       for d in devices[:30]) or "none known"
    current = ", ".join(f"{k}={context[k]}" for k in ("host_name", "device_id", "userinterface_name", "current_page")
                        if context.get(k)) or "none"
    return ("You are the quick-command layer of Atlas, the assistant of a device-test lab app. The user wrote or "
            "said one short command. Call exactly one tool when it is one simple command that a listed tool does "
            "directly. Use ask_atlas for anything else (questions, several steps, unclear). Never guess a device: use "
            "only these, with their exact host_name and device_id. Arguments in English: page names as the app "
            "labels them (devices, dashboard, heatmap, test reports…), node names as in the navigation tree. "
            f"Known devices: {listed}. Current: {current}.")


def parse_response(response: Any) -> tuple[str, str, dict]:
    """(kind, tool, input): kind is 'tool' for the first tool_use block, else 'text'."""
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            return "tool", block.name, dict(block.input or {})
    return "text", "", {}


def tool_text(result: Any, limit: int = 500) -> str:
    """Plain text of an MCP-style tool result."""
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        text = " ".join(c.get("text", "") for c in result["content"] if isinstance(c, dict) and c.get("type") == "text")
    elif isinstance(result, dict) and isinstance(result.get("result"), str):  # page tools: {"result": "..."}
        text = result["result"]
    else:
        text = str(result or "")
    return " ".join(text.split())[:limit]


def summary_line(tool: str, args: dict, result: Any) -> str:
    """The assistant line saved to the session so the next turn knows what happened."""
    detail = tool_text(result, 300)
    if tool in ("show_page", "navigate_to_page"):
        page = args.get("page") or args.get("page_name") or ""
        return f"Opened {page}." + (f" {detail}" if detail else "")
    shown = ", ".join(f"{k}={v}" for k, v in args.items() if not isinstance(v, (dict, list)))
    return f"{tool} ({shown})." + (f" {detail}" if detail else "")


# ------------------------------------------------------------------ counters (fire and forget)

def record(kind: str, team_id: str, user_id: str, tool: str) -> None:
    """Count a 'use' / 'hit' / 'miss' on a background thread so the turn never waits for the database."""
    if not (team_id and user_id and tool):
        return

    def _run():
        try:
            from shared.src.lib.database import atlas_quick_stats_db as stats_db
            {"use": stats_db.add_use, "hit": stats_db.add_hit, "miss": stats_db.add_miss}[kind](team_id, user_id, tool)
        except Exception:  # noqa: BLE001 - statistics never break a turn
            pass
    threading.Thread(target=_run, daemon=True).start()

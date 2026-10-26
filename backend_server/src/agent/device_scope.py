"""Which devices an agent may act on in this turn (BUG-0914).

On 2026-10-25 Atlas, asked the vague "cap 5" with one phone in the page context, listed every host, took
control of a Tello drone and of two shared host desktops (one of them labox-web) and ran shell commands
there. The page context was a hint in the prompt, not a boundary. This module is the boundary, checked by
the tool bridge before any device ACTION runs (reads are not gated):

1. **The page's devices.** When the chat sent its device list, an action on a device outside it is refused
   (the chat's selected Target always counts).
2. **Drones.** A drone tool, or any action on a drone device, only when the user named that device or said
   "drone" / "tello" / "fly" … in this message, or it is the selected Target.
3. **Host desktops.** An action on a host's own desktop (device ``host``) only when the user named that host
   in this message, or it is the selected Target.
4. **Shell commands.** ``execute_bash_command`` only when the user asked for a command in this message.

A refusal is returned to the model as a tool error with the reason, so it asks the user instead of
retrying elsewhere. Pure functions; the bridge passes the session context and the user's message.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

DRONE_TOOLS = frozenset({"takeoff", "land", "emergency", "move", "rotate", "flip", "set_speed"})
# Actions only. Reads (capture_screenshot, dump_ui_elements, list_actions, get_device_info …) are not gated.
GUARDED_TOOLS = frozenset({
    "take_control", "execute_device_action", "navigate_to_node", "execute_testcase", "execute_testcase_by_id",
    "execute_edge", "execute_group_action", "execute_script", "execute_campaign", "save_node_screenshot",
}) | DRONE_TOOLS
DRONE_MODELS = ("tello", "drone")
_DRONE_WORDS = ("drone", "tello", "fly ", "flight", "take off", "takeoff", "land ", "hover")
_SHELL_WORDS = ("bash", "shell", "terminal", "command", "cmd", "run `", "execute `", "script on the host")


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _bash_requested(params: Mapping[str, Any]) -> bool:
    actions = params.get("actions") or []
    if isinstance(actions, dict):
        actions = [actions]
    return any(isinstance(a, dict) and a.get("command") == "execute_bash_command" for a in actions)


def refusal(tool_name: str, params: Mapping[str, Any], context: Mapping[str, Any],
            message: str) -> Optional[str]:
    """None when the action may run, else why not (sent back to the model as a tool error)."""
    if tool_name not in GUARDED_TOOLS:
        return None
    msg = " " + _norm(message) + " "
    host = str(params.get("host_name") or "")
    device = str(params.get("device_id") or "")
    devices = [d for d in (context.get("available_devices") or []) if isinstance(d, dict)]
    selected = (str(context.get("host_name") or ""), str(context.get("device_id") or ""))
    is_selected = bool(host) and host == selected[0] and (not device or device == selected[1] or not selected[1])
    entry = next((d for d in devices if d.get("host_name") == host and d.get("device_id") == device), None)
    name = _norm((entry or {}).get("device_name"))
    named = {_norm(n.get("device_name")) for n in (context.get("named_devices") or [])
             if isinstance(n, dict) and n.get("device_name")}
    device_named = bool(name) and (name in named or f" {name} " in msg or name in msg)

    if devices and host and device and device != "host" and entry is None and not is_selected:
        return (f"{host}/{device} is not one of the devices of this chat. Ask the user which device they mean "
                "before acting on another one.")
    model = _norm((entry or {}).get("device_model"))
    if tool_name in DRONE_TOOLS or any(m in model for m in DRONE_MODELS):
        if not (is_selected or device_named or any(w in msg for w in _DRONE_WORDS)):
            return (f"{host}/{device} is a drone. A drone is only flown when the user names it or asks for the "
                    "drone in this message: ask the user first.")
    if device == "host" and not is_selected and not (host and _norm(host) in msg):
        return (f"the desktop of {host} is a shared host, not a test device. It is only used when the user names "
                f"{host} in this message: ask the user first.")
    if _bash_requested(params) and not any(w in msg for w in _SHELL_WORDS):
        return ("shell commands on a host run only when the user asks for a command in this message. Answer "
                "with what you would run and ask the user to confirm.")
    return None


def last_user_message(messages: Iterable[Mapping[str, Any]]) -> str:
    """The last user message of the session history ('' when none)."""
    for item in reversed(list(messages or [])):
        if item.get("role") == "user":
            content = item.get("content")
            return content if isinstance(content, str) else ""
    return ""

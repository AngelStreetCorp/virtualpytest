"""Deterministic handling of devices the user named in a chat message (BUG-0323/0331/0355).

Pure functions, no I/O: the agent pipeline detects mentions, the analytics tools enforce them.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


def _pattern(name: str) -> "re.Pattern[str]":
    words = str(name).split()
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(w) for w in words) + r"(?!\w)", re.IGNORECASE)


def find_mentions(text: str, names: Iterable[str]) -> List[str]:
    """Known names that appear in ``text`` as whole phrases (case-insensitive), in text order.

    Longer names win overlapping spans, so 'Phone' inside 'Phone slot 1' is not a second mention and
    'host' does not match inside 'hosts'.
    """
    unique = sorted({str(n).strip() for n in names if n and str(n).strip()}, key=lambda n: (-len(n), n))
    taken: List[Tuple[int, int]] = []
    found: List[Tuple[int, str]] = []
    for name in unique:
        for match in _pattern(name).finditer(text or ""):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue
            taken.append(span)
            found.append((span[0], name))
            break
    return [name for _, name in sorted(found)]


# Device names that are also everyday words ("pass rate per host"): a plain mention of one is not a
# request for that device, so it never becomes a filter. Names with a digit, hyphen or space are specific.
GENERIC_NAMES = frozenset({"host", "hosts", "device", "devices", "phone", "mobile", "tv", "stb", "box", "server",
                           "web", "tablet", "android", "ios", "desktop", "browser", "emulator", "player", "all"})


def detect_named_devices(message: str, devices: Sequence[Mapping[str, Any]],
                         server_hosts: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """Classify each device the message names as on the selected server or not.

    ``devices`` are every device the server knows (any server); with no known server hosts nothing can be
    classified off-server, so every mention counts as on-server.
    """
    hosts = {str(h) for h in server_hosts or [] if h}
    by_name: Dict[str, Dict[str, Any]] = {}
    for device in devices or []:
        name = str(device.get("device_name") or "").strip()
        if not name or name.lower() in GENERIC_NAMES:
            continue
        on_server = not hosts or str(device.get("host_name") or "") in hosts
        entry = by_name.setdefault(name, {"name": name, "host_name": str(device.get("host_name") or ""),
                                          "on_server": False})
        if on_server and not entry["on_server"]:
            entry.update(on_server=True, host_name=str(device.get("host_name") or ""))
    return [by_name[name] for name in find_mentions(message, by_name)]


def named_devices_line(named: Sequence[Mapping[str, Any]], server_name: str = "") -> str:
    """The context line for the router prompt; empty when the user named no device."""
    if not named:
        return ""
    where = f"the selected server {server_name}" if server_name else "the selected server"
    parts = [f"'{d['name']}' ({'on this server' if d.get('on_server') else 'not on ' + where})" for d in named]
    return ("**User named devices:** " + ", ".join(parts) + ". The analytics tools filter to the named devices "
            "on this server automatically and refuse to chart other devices when none is on this server; "
            "report that to the user instead of substituting.\n\n")


def split_named(named: Iterable[Mapping[str, Any]]) -> Tuple[List[str], List[str]]:
    on, off = [], []
    for device in named or []:
        (on if device.get("on_server") else off).append(str(device.get("name")))
    return on, off


# "my selected devices", "this device", "the target"...: a reference to the chat's Target device (BUG-0405).
# Whole phrases only: a bare "devices" or "by device" is not a reference.
_SELECTED_REFERENCE = re.compile(
    r"(?<!\w)(?:selected\s+devices?|my\s+(?:selected\s+|current\s+|target\s+)?devices?"
    r"|(?:this|current|the\s+current|the\s+selected|the\s+target)\s+device|the\s+target)(?!\w)",
    re.IGNORECASE)


def refers_to_selected_device(message: str) -> bool:
    """True when the message points at the chat's Target device ("on my selected device", "this device")."""
    return bool(_SELECTED_REFERENCE.search(message or ""))


def selected_device_state(message: str, ctx: Mapping[str, Any]) -> Dict[str, Any]:
    """Session-context fields for a message that refers to the selected device.

    ``refers_to_selected_device`` is true only when a current device is set AND on the selected server
    (the BUG-0311 foreign check); ``selected_device`` then carries its host/id/name. A reference to a
    Target that is foreign (or whose server hosts are unknown-but-excluding it) sets
    ``selected_device_foreign`` so the reply can say the Target is not on this server.
    """
    state: Dict[str, Any] = {"refers_to_selected_device": False, "selected_device": None,
                             "selected_device_foreign": False}
    if not refers_to_selected_device(message):
        return state
    host, device_id = ctx.get("host_name"), ctx.get("device_id")
    if not (host and device_id):
        return state
    server_hosts = ctx.get("selected_server_hosts") or []
    if server_hosts and host not in server_hosts:
        state["selected_device_foreign"] = True
        state["selected_device"] = {"host_name": str(host), "device_id": str(device_id), "device_name": ""}
        return state
    name = next((str(d.get("device_name")) for d in ctx.get("available_devices") or []
                 if isinstance(d, dict) and d.get("host_name") == host and d.get("device_id") == device_id
                 and d.get("device_name")), "")
    state.update(refers_to_selected_device=True,
                 selected_device={"host_name": str(host), "device_id": str(device_id), "device_name": name})
    return state

"""Who is calling an MCP device tool, and is the lock on the device theirs?

The MCP device tools (execute_device_action, navigate_to_node, execute_testcase) take the
device lock themselves. When the device is already locked they may only run under a lock
that belongs to the caller - never under someone else's Take Control (BUG-0402).

Caller identity, in order:
- ``session_id`` - an explicit session (the one ``take_control`` returned to an MCP client).
  Atlas always sets it to the chat session id (tool_bridge), so the model cannot pick one.
- ``_caller_browser_session_id`` - the browser tab the Atlas chat was sent from (its Take
  Control uses that id). Set by tool_bridge only.
- ``_caller_user_id`` - the signed-in user behind the Atlas chat; left empty for shared
  principals (auto-sign, open mode, service key), where every caller has the same id.
- No identity at all (a plain MCP client): the session this MCP server's own ``take_control``
  opened on that device, if any.
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple

# Sessions opened by take_control for MCP callers that gave no session_id: "host:device" -> id.
# Every such caller authenticates with the same MCP secret, so they are one identity.
_ANONYMOUS_MCP_SESSIONS: Dict[str, str] = {}

# Tools that take, use or release a device lock for their caller (tool_bridge injects identity).
DEVICE_LOCK_TOOL_NAMES = frozenset({
    "take_control", "release_control", "execute_device_action", "navigate_to_node", "execute_testcase",
})

EXECUTION_OWNER_TYPES = ('script_execution', 'deployment_execution', 'testcase_execution')


def device_key(host_name: str, device_id: str) -> str:
    return f"{host_name}:{device_id}"


def remember_anonymous_session(host_name: str, device_id: str, session_id: str) -> None:
    _ANONYMOUS_MCP_SESSIONS[device_key(host_name, device_id)] = session_id


def anonymous_session(host_name: str, device_id: str) -> Optional[str]:
    return _ANONYMOUS_MCP_SESSIONS.get(device_key(host_name, device_id))


def forget_anonymous_session(host_name: str, device_id: str) -> None:
    _ANONYMOUS_MCP_SESSIONS.pop(device_key(host_name, device_id), None)


def caller_identity(params: Dict[str, Any], host_name: str, device_id: str) -> Tuple[List[str], Optional[str]]:
    """(session ids that are the caller's, caller user id or None)."""
    sessions = [s for s in (params.get('session_id'), params.get('_caller_browser_session_id')) if s]
    user_id = params.get('_caller_user_id') or None
    if not sessions and not user_id:
        anonymous = anonymous_session(host_name, device_id)
        if anonymous:
            sessions.append(anonymous)
    return sessions, user_id


def _lock_field(result: Dict[str, Any], field: str) -> Optional[str]:
    return result.get(field) or (result.get('lock_info') or {}).get(field)


def is_own_lock(conflict: Dict[str, Any], sessions: List[str], user_id: Optional[str]) -> bool:
    """True when a takeControl 423 names a lock the caller holds itself."""
    owner_session = _lock_field(conflict, 'owner_session_id')
    owner_user = _lock_field(conflict, 'owner_user_id')
    return bool(owner_session and owner_session in sessions) or bool(user_id and owner_user == user_id)


def holder(conflict: Dict[str, Any]) -> str:
    """A human name for whoever holds the lock."""
    return (_lock_field(conflict, 'owner_user_name') or _lock_field(conflict, 'owner_user_id')
            or _lock_field(conflict, 'owner_session_id') or 'another session')


def _error(text: str, error_type: Optional[str] = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": True}
    if error_type:
        err["errorType"] = error_type
    return err


def auto_lock(api, held: Dict[str, str], params: Dict[str, Any], host_name: str, device_id: str,
              team_id: str, force_unlock: bool, tag: str) -> Optional[Dict[str, Any]]:
    """Lock the device for one tool call. Returns an MCP error dict, or None to proceed.

    ``held`` records locks this call acquired (released by the caller's ``_auto_unlock``).
    The device runs under the caller's own lock (no record, so it is not released) and is
    refused - naming the holder - when anyone else holds it. ``force_unlock`` only stops a
    running script/deployment/testcase; another person's Take Control is never taken.
    """
    sessions, user_id = caller_identity(params, host_name, device_id)
    session_id = sessions[0] if sessions else f"mcp-{tag}-{uuid.uuid4()}"
    data = {'host_name': host_name, 'device_id': device_id, 'session_id': session_id}
    if user_id:
        data['user_id'] = user_id
    query = {'team_id': team_id}

    result = api.post('/server/control/takeControl', data=data, params=query)

    if (not result.get('success') and result.get('errorType') == 'device_locked' and force_unlock
            and _lock_field(result, 'owner_type') in EXECUTION_OWNER_TYPES):
        # Explicit opt-in: stop the running execution, then take the device.
        result = api.post('/server/control/takeover', data={
            'host_name': host_name,
            'device_id': device_id,
            'requested_by_session': session_id,
            'stop_running_execution': True,
            'reason': 'mcp_force_unlock',
        }, params=query)

    if result.get('success'):
        if not result.get('reused'):
            held[device_key(host_name, device_id)] = session_id
        return None

    if result.get('errorType') != 'device_locked':
        return _error(f"Failed to lock device: {result.get('error', 'Unknown error')}")

    if is_own_lock(result, sessions, user_id):
        print(f"[@MCP:auto_lock:{tag}] {device_key(host_name, device_id)} held by the caller — running under it")
        return None

    owner_type = _lock_field(result, 'owner_type') or 'unknown'
    text = (f"Device '{device_id}' on host '{host_name}' is in use by {holder(result)} ({owner_type}). "
            "Not taking it over - wait until they release it or ask them to.")
    if owner_type in EXECUTION_OWNER_TYPES:
        text += " To stop their running execution, retry with force_unlock=true."
    return _error(text, 'device_locked')

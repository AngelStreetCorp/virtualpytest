"""
Server System Socket Routes

Socket.IO namespace for system state updates (hosts, locks, health).
This enables progressive migration away from frontend polling.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from flask import current_app, request
from flask_socketio import join_room

from backend_server.src.lib import socket_auth, socket_presence
from backend_server.src.lib.auth_middleware import authorize_socket_connection, team_ids_for_principal

_socketio = None
SYSTEM_NAMESPACE = "/system"
# A signed-in user joins one room per team it belongs to; the shared principals (service key,
# auto-sign, open mode, public key) are deployment-wide and join the all-teams room.
TEAM_ROOM_PREFIX = "team:"
ALL_TEAMS_ROOM = "teams:all"
PRESENCE_UPDATE = "presence_changed"


def team_room(team_id: Any) -> str:
    return f"{TEAM_ROOM_PREFIX}{team_id}"


def init_system_socketio(socketio) -> None:
    """Store Socket.IO instance for later emits."""
    global _socketio
    _socketio = socketio


def emit_system_update(update_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """
    Send a system update to the /system clients allowed to see it.

    A payload carrying `team_id` goes to that team's room and to the all-teams room only, so
    one team's runs, agent work and presence never reach another team's browsers. A payload
    without `team_id` (hosts, locks: fleet-level state) is broadcast as before.

    Args:
        update_type: Logical update reason (e.g., "host_registered", "lock_changed")
        payload: Optional additional metadata
    """
    socketio = _socketio

    # Fallback for mixed import paths (e.g. routes.* vs backend_server.src.routes.*):
    # resolve socketio from Flask app context if module-level singleton is unset.
    if socketio is None:
        try:
            socketio = getattr(current_app, "socketio", None)
        except Exception:
            socketio = None

    if socketio is None:
        return

    data: Dict[str, Any] = {"type": update_type}
    if payload:
        data.update(payload)
    team_id = data.get("team_id")
    if team_id:
        # Room memberships are disjoint (a person is never in the all-teams room), so no
        # client receives the update twice.
        socketio.emit("system_update", data, namespace=SYSTEM_NAMESPACE, to=team_room(team_id))
        socketio.emit("system_update", data, namespace=SYSTEM_NAMESPACE, to=ALL_TEAMS_ROOM)
    else:
        socketio.emit("system_update", data, namespace=SYSTEM_NAMESPACE)


def _emit_presence(team_ids) -> None:
    for team_id in team_ids:
        emit_system_update(PRESENCE_UPDATE, socket_presence.snapshot(team_id))


def _sees_every_team(principal: dict) -> bool:
    """Admins and platform admins may act on any team (enforce_team_scope exempts them)."""
    app_meta = principal.get("user_app_metadata") or {}
    return principal.get("user_role") == "admin" or bool(app_meta.get("is_platform_admin"))


def _join_rooms(principal: dict) -> set:
    """Join the rooms this principal may read; returns its team ids (empty for a shared one)."""
    if principal.get("shared"):
        join_room(ALL_TEAMS_ROOM, namespace=SYSTEM_NAMESPACE)
        return set()
    team_ids = team_ids_for_principal(principal)
    if _sees_every_team(principal):
        # One room only: joining the team rooms too would deliver every update twice.
        join_room(ALL_TEAMS_ROOM, namespace=SYSTEM_NAMESPACE)
    else:
        for team_id in team_ids:
            join_room(team_room(team_id), namespace=SYSTEM_NAMESPACE)
    return team_ids


def register_system_socketio_handlers(socketio) -> None:
    """Register Socket.IO handlers for system namespace."""

    @socketio.on("connect", namespace=SYSTEM_NAMESPACE)
    def handle_connect(auth=None):
        """Authenticate the handshake, or refuse the connection.

        This namespace broadcasts the fleet's live state — which hosts and devices exist,
        which are locked and by whom, deployment progress. The socket.io handshake never
        passes through the global /server/* guard, so all of it was readable by anyone who
        could open a socket, on a deployment whose HTTP API is closed.

        Returning False refuses the connection; the client sees a connect_error.
        """
        principal = authorize_socket_connection(auth)
        if principal is None:
            print(f"[@system_socket] ⛔ refused unauthenticated connection to {SYSTEM_NAMESPACE}")
            return False

        socket_auth.remember(request.sid, principal)
        team_ids = _join_rooms(principal)
        socket_presence.add(request.sid, principal, team_ids)
        socketio.emit(
            "connected",
            {"status": "ok", "namespace": SYSTEM_NAMESPACE},
            namespace=SYSTEM_NAMESPACE,
            to=request.sid,
        )
        _emit_presence(socket_presence.teams_of({"shared": bool(principal.get("shared")), "team_ids": team_ids}))
        return None

    @socketio.on("disconnect", namespace=SYSTEM_NAMESPACE)
    def handle_disconnect():
        socket_auth.forget(request.sid)
        _emit_presence(socket_presence.teams_of(socket_presence.remove(request.sid)))
        return None


def register_default_namespace_guard(socketio) -> None:
    """Authenticate the default ('/') namespace.

    It carries no handlers of its own, which is exactly why it was open: with no connect
    handler registered, socket.io accepts every client. It is not idle though —
    `server_web_routes.task_complete` emits `task_complete` with no namespace, so browser
    automation results are delivered here and were readable by anyone who connected.
    """

    @socketio.on("connect")
    def handle_default_connect(auth=None):
        principal = authorize_socket_connection(auth)
        if principal is None:
            print("[@system_socket] ⛔ refused unauthenticated connection to the default namespace")
            return False
        socket_auth.remember(request.sid, principal)
        return None

    @socketio.on("disconnect")
    def handle_default_disconnect():
        socket_auth.forget(request.sid)
        return None

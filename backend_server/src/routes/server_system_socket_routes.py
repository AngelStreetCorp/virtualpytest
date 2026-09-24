"""
Server System Socket Routes

Socket.IO namespace for system state updates (hosts, locks, health).
This enables progressive migration away from frontend polling.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from flask import current_app, request

from backend_server.src.lib import socket_auth
from backend_server.src.lib.auth_middleware import authorize_socket_connection

_socketio = None
SYSTEM_NAMESPACE = "/system"


def init_system_socketio(socketio) -> None:
    """Store Socket.IO instance for later emits."""
    global _socketio
    _socketio = socketio


def emit_system_update(update_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """
    Broadcast a system update event to all connected /system clients.

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
    socketio.emit("system_update", data, namespace=SYSTEM_NAMESPACE)


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
        socketio.emit(
            "connected",
            {"status": "ok", "namespace": SYSTEM_NAMESPACE},
            namespace=SYSTEM_NAMESPACE,
            to=request.sid,
        )
        return None

    @socketio.on("disconnect", namespace=SYSTEM_NAMESPACE)
    def handle_disconnect():
        socket_auth.forget(request.sid)
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

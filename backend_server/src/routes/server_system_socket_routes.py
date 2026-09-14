"""
Server System Socket Routes

Socket.IO namespace for system state updates (hosts, locks, health).
This enables progressive migration away from frontend polling.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from flask import current_app, request

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
    def handle_connect():
        socketio.emit(
            "connected",
            {"status": "ok", "namespace": SYSTEM_NAMESPACE},
            namespace=SYSTEM_NAMESPACE,
            to=request.sid,
        )

    @socketio.on("disconnect", namespace=SYSTEM_NAMESPACE)
    def handle_disconnect():
        # No-op for now. Keep handler for observability extension later.
        return None

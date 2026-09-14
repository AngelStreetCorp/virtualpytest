"""
Socket Manager for handling WebSocket communications
"""
import logging
from typing import Dict, Any, Optional
from flask_socketio import SocketIO

logger = logging.getLogger(__name__)

class SocketManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SocketManager, cls).__new__(cls)
            cls._instance.socketio = None
        return cls._instance

    def init_app(self, socketio: SocketIO):
        """Initialize with Flask-SocketIO instance"""
        self.socketio = socketio
        logger.info("SocketManager initialized with SocketIO instance")

    def emit_to_room(self, room: str, event: str, data: Dict[str, Any], namespace: str = '/agent'):
        """Emit event to a specific room"""
        if not self.socketio:
            logger.warning("SocketIO not initialized, cannot emit event")
            return

        try:
            self.socketio.emit(event, data, room=room, namespace=namespace)
            logger.debug(f"Emitted {event} to room {room}")
        except Exception as e:
            logger.error(f"Failed to emit event {event}: {e}")

    def broadcast(self, event: str, data: Dict[str, Any], namespace: str = '/agent'):
        """Broadcast event to all connected clients in namespace"""
        if not self.socketio:
            logger.warning("🔴 SocketIO not initialized, cannot broadcast")
            return False

        try:
            logger.info(f"🟢 Broadcasting '{event}' to namespace '{namespace}': {data}")
            self.socketio.emit(event, data, namespace=namespace)
            logger.info(f"🟢 Broadcast complete!")
            return True
        except Exception as e:
            logger.error(f"🔴 Failed to broadcast {event}: {e}")
            return False

# Global instance
socket_manager = SocketManager()


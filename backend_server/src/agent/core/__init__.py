"""
Agent Core Components

- Manager: QA Manager orchestrator
- Session: Chat session management
- ToolBridge: MCP tool integration
- MessageTypes: Event types for streaming
"""

# Lightweight imports only - no MCP dependencies
from .session import Session, SessionManager
from .message_types import EventType, AgentEvent

__all__ = [
    'Session',
    'SessionManager',
    'EventType',
    'AgentEvent',
]



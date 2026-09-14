"""
Message Types for Agent Communication

Defines event types streamed to frontend.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime


class EventType(str, Enum):
    """Types of events streamed to frontend"""
    
    # Agent lifecycle
    THINKING = "thinking"           # Agent reasoning
    TOOL_CALL = "tool_call"         # Tool being called
    TOOL_RESULT = "tool_result"     # Tool result
    MESSAGE = "message"             # Agent message to user
    RESULT = "result"               # Final result from agent
    
    # Flow control
    MODE_DETECTED = "mode_detected"         # Operating mode identified
    AGENT_STARTED = "agent_started"         # New agent starting (creates new message bubble)
    AGENT_DELEGATED = "agent_delegated"     # Task delegated to agent (QA Manager says "delegating...")
    AGENT_COMPLETED = "agent_completed"     # Agent finished task (closes current message bubble)
    SKILL_LOADED = "skill_loaded"           # Skill dynamically loaded
    SKILL_UNLOADED = "skill_unloaded"       # Skill unloaded, back to router mode
    
    # Human interaction
    APPROVAL_REQUIRED = "approval_required"  # Need human approval
    APPROVAL_RECEIVED = "approval_received"  # Human approved/rejected
    
    # Progress
    PROGRESS = "progress"           # Progress update (3/10)
    
    # Session
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    
    # Errors
    ERROR = "error"

    # Debug information
    SYSTEM_PROMPT = "system_prompt"
    CONVERSATION_CONTEXT = "conversation_context"
    TOOL_DEFINITIONS = "tool_definitions"


@dataclass
class AgentEvent:
    """Event from agent to frontend"""
    
    type: EventType
    agent: str  # Which agent produced this
    content: Any  # Event payload
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Optional fields
    tool_name: Optional[str] = None
    tool_params: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None
    success: Optional[bool] = None
    error: Optional[str] = None
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    approval_id: Optional[str] = None
    approval_options: Optional[list] = None
    metrics: Optional[Dict[str, Any]] = None  # {duration_ms, input_tokens, output_tokens}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {
            "type": self.type.value,
            "agent": self.agent,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
        
        # Add optional fields if set
        if self.tool_name:
            result["tool_name"] = self.tool_name
        if self.tool_params:
            result["tool_params"] = self.tool_params
        if self.tool_result is not None:
            result["tool_result"] = self.tool_result
        if self.success is not None:
            result["success"] = self.success
        if self.error:
            result["error"] = self.error
        if self.progress_current is not None:
            result["progress"] = {
                "current": self.progress_current,
                "total": self.progress_total,
            }
        if self.approval_id:
            result["approval"] = {
                "id": self.approval_id,
                "options": self.approval_options or [],
            }
        if self.metrics:
            result["metrics"] = self.metrics
            
        return result


@dataclass 
class ApprovalRequest:
    """Request for human approval"""
    
    id: str
    agent: str
    action: str  # What needs approval
    options: list  # Approval options
    context: Dict[str, Any]  # Additional context
    default_option: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent,
            "action": self.action,
            "options": self.options,
            "context": self.context,
            "default_option": self.default_option,
        }


@dataclass
class ApprovalResponse:
    """Human response to approval request"""
    
    approval_id: str
    selected_option: str
    modifications: Optional[Dict[str, Any]] = None  # User modifications

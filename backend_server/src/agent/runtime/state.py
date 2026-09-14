"""
Agent Instance State Management

Tracks state of running agent instances in memory and database.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class AgentState(str, Enum):
    """Agent instance states"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentInstanceState:
    """In-memory state of an agent instance"""
    instance_id: str
    agent_id: str
    version: str
    state: AgentState
    current_task: Optional[str] = None
    task_id: Optional[str] = None
    started_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    error_message: Optional[str] = None
    team_id: str = 'default'
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.started_at is None:
            self.started_at = datetime.utcnow()
        if self.last_activity is None:
            self.last_activity = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'instance_id': self.instance_id,
            'agent_id': self.agent_id,
            'version': self.version,
            'state': self.state.value if isinstance(self.state, AgentState) else self.state,
            'current_task': self.current_task,
            'task_id': self.task_id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'error_message': self.error_message,
            'team_id': self.team_id,
            'metadata': self.metadata
        }
    
    def update_state(self, new_state: AgentState, task: Optional[str] = None, task_id: Optional[str] = None):
        """Update instance state"""
        self.state = new_state
        self.last_activity = datetime.utcnow()
        
        if task is not None:
            self.current_task = task
        if task_id is not None:
            self.task_id = task_id
        
        if new_state == AgentState.IDLE:
            self.current_task = None
            self.task_id = None
            self.error_message = None
    
    def set_error(self, error_message: str):
        """Set error state"""
        self.state = AgentState.ERROR
        self.error_message = error_message
        self.last_activity = datetime.utcnow()


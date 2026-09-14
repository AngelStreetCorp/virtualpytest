"""
Event Router

Routes events to appropriate agents based on event type and agent triggers.
Integrates with Agent Registry to find matching agents.
"""

from typing import List, Dict, Any

from agent.registry import AgentRegistry, get_agent_registry
from events.event_bus import EventBus, Event, EventPriority, get_event_bus
from shared.src.lib.database import events_db


class EventRouter:
    """
    Event Router
    
    Routes incoming events to agents that should handle them.
    Logs routing decisions and unhandled events.
    """
    
    def __init__(
        self,
        event_bus: EventBus = None,
        registry: AgentRegistry = None
    ):
        """
        Initialize Event Router
        
        Args:
            event_bus: Event bus for publishing (optional)
            registry: Agent registry for lookup (optional)
        """
        self.event_bus = event_bus or get_event_bus()
        self.registry = registry or get_agent_registry()
    
    async def route_event(self, event: Event) -> bool:
        """
        Route event to appropriate agents
        
        Args:
            event: Event to route
            
        Returns:
            True if routed to at least one agent, False if unhandled
        """
        # Get agents that should handle this event (sync call)
        agents = self.registry.get_agents_for_event(
            event.type,
            event.team_id
        )
        
        if not agents:
            # No agents registered for this event
            self._log_unhandled(event)
            
            # Publish unhandled event notification
            await self.event_bus.publish(Event(
                type="event.unhandled",
                payload={
                    "event_type": event.type,
                    "event_id": event.id
                },
                priority=EventPriority.LOW,
                team_id=event.team_id
            ))
            
            print(f"[@router] ⚠️ Unhandled: {event.type} (no agents registered)")
            return False
        
        # Publish event for registered agents
        await self.event_bus.publish(event)
        
        print(f"[@router] ✅ Routed: {event.type} → {len(agents)} agent(s)")
        
        return True
    
    def get_routing_stats(self, team_id: str = 'default') -> Dict[str, Any]:
        """
        Get event routing statistics
        
        Args:
            team_id: Team namespace
            
        Returns:
            Statistics dictionary
        """
        return events_db.get_routing_stats(team_id)
    
    def get_event_types(self, team_id: str = 'default') -> List[str]:
        """
        Get list of all event types seen
        
        Args:
            team_id: Team namespace
            
        Returns:
            List of event type strings
        """
        return events_db.get_event_types(team_id)
    
    def _log_unhandled(self, event: Event):
        """Log unhandled event"""
        print(f"[@router] 📝 Logged unhandled event: {event.type}")


# Global instance
_event_router = None

def get_event_router() -> EventRouter:
    """Get or create global event router instance"""
    global _event_router
    if _event_router is None:
        _event_router = EventRouter()
    return _event_router

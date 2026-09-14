"""
Event Bus - Central Pub/Sub System

Provides Redis-based event distribution for the multi-agent platform.
All events flow through this bus and are logged to PostgreSQL.
"""

import asyncio
import json
import os
from typing import Callable, Dict, List, Any, Optional
from enum import Enum
from datetime import datetime
from dataclasses import dataclass, asdict
import redis.asyncio as redis

from shared.src.lib.database import events_db


class EventPriority(Enum):
    """Event priority levels"""
    CRITICAL = 1  # Immediate action required (blackscreen, crash)
    HIGH = 2      # Prompt attention (build deployed, test failure)
    NORMAL = 3    # Standard processing (scheduled regression)
    LOW = 4       # Background processing (metrics collection)


@dataclass
class Event:
    """Event data structure"""
    type: str                    # Event type (e.g., 'alert.blackscreen')
    payload: Dict[str, Any]      # Event data
    priority: EventPriority      # Priority level
    id: Optional[str] = None     # Unique event ID
    timestamp: Optional[datetime] = None  # When event occurred
    team_id: str = 'default'     # Team namespace
    
    def __post_init__(self):
        if self.id is None:
            timestamp_ms = int(datetime.utcnow().timestamp() * 1000)
            self.id = f"evt_{timestamp_ms}"
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'id': self.id,
            'type': self.type,
            'payload': self.payload,
            'priority': self.priority.value,
            'timestamp': self.timestamp.isoformat(),
            'team_id': self.team_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """Create Event from dictionary"""
        return cls(
            id=data['id'],
            type=data['type'],
            payload=data['payload'],
            priority=EventPriority(data['priority']),
            timestamp=datetime.fromisoformat(data['timestamp']),
            team_id=data.get('team_id', 'default')
        )


class EventBus:
    """
    Redis-based Event Bus
    
    Provides pub/sub for event distribution and logs all events to PostgreSQL.
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize Event Bus
        
        Args:
            redis_url: Redis connection URL (default: from environment)
        """
        self.redis_url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379')
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self.subscribers: Dict[str, List[Callable]] = {}
        self.running = False
        self._listen_task: Optional[asyncio.Task] = None
    
    async def connect(self):
        """Connect to Redis"""
        if self.redis_client is not None:
            return
        
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            await self.redis_client.ping()
            print(f"[@event_bus] ✅ Connected to Redis at {self.redis_url}")
        except Exception as e:
            print(f"[@event_bus] ❌ Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from Redis"""
        self.running = False
        
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        
        if self.pubsub:
            await self.pubsub.close()
        
        if self.redis_client:
            await self.redis_client.close()
            self.redis_client = None
        
        print("[@event_bus] Disconnected from Redis")
    
    async def publish(self, event: Event) -> None:
        """
        Publish event to all subscribers
        
        Args:
            event: Event to publish
        """
        if self.redis_client is None:
            await self.connect()
        
        # Log event to database (sync call)
        self._log_event(event)
        
        # Publish to Redis
        event_json = json.dumps(event.to_dict())
        channel = f"events:{event.type}"
        
        try:
            await self.redis_client.publish(channel, event_json)
            print(f"[@event_bus] 📤 Published: {event.type} (id={event.id}, priority={event.priority.name})")
        except Exception as e:
            print(f"[@event_bus] ❌ Failed to publish event: {e}")
            raise
    
    async def subscribe(self, event_type: str, callback: Callable) -> None:
        """
        Subscribe to event type
        
        Args:
            event_type: Event type pattern (e.g., 'alert.blackscreen')
            callback: Async function to call when event received
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        
        self.subscribers[event_type].append(callback)
        print(f"[@event_bus] 📥 Subscribed to: {event_type}")
    
    async def start(self):
        """Start listening for events"""
        if self.running:
            return
        
        if self.redis_client is None:
            await self.connect()
        
        self.running = True
        self.pubsub = self.redis_client.pubsub()
        
        # Subscribe to all registered event types
        channels = [f"events:{event_type}" for event_type in self.subscribers.keys()]
        if channels:
            await self.pubsub.subscribe(*channels)
            print(f"[@event_bus] 🎧 Listening on {len(channels)} channels")
        
        # Start listening task
        self._listen_task = asyncio.create_task(self._listen())
    
    async def _listen(self):
        """Listen for incoming events"""
        try:
            async for message in self.pubsub.listen():
                if not self.running:
                    break
                
                if message['type'] == 'message':
                    await self._handle_message(message)
        except asyncio.CancelledError:
            print("[@event_bus] Listener cancelled")
        except Exception as e:
            print(f"[@event_bus] ❌ Listener error: {e}")
    
    async def _handle_message(self, message: Dict[str, Any]):
        """Handle incoming message"""
        try:
            # Parse event
            event_data = json.loads(message['data'])
            event = Event.from_dict(event_data)
            
            # Get event type from channel name
            channel = message['channel']
            event_type = channel.replace('events:', '')
            
            # Call all subscribers for this event type
            callbacks = self.subscribers.get(event_type, [])
            
            for callback in callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    print(f"[@event_bus] ❌ Callback error for {event_type}: {e}")
        
        except Exception as e:
            print(f"[@event_bus] ❌ Failed to handle message: {e}")
    
    def _log_event(self, event: Event):
        """Log event to database (sync)"""
        try:
            events_db.log_event(
                event_id=event.id,
                event_type=event.type,
                payload=event.payload,
                priority=event.priority.value,
                timestamp=event.timestamp,
                team_id=event.team_id
            )
        except Exception as e:
            print(f"[@event_bus] ⚠️ Failed to log event to database: {e}")
            # Don't raise - event publishing should continue even if logging fails


# Global instance
_event_bus: Optional[EventBus] = None

def get_event_bus() -> EventBus:
    """Get or create global event bus instance"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus

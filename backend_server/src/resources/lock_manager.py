"""
Resource Lock Manager

Manages exclusive locks on resources (devices, trees, userinterfaces)
to enable safe parallel execution. Includes priority-based queuing.
"""

import asyncio
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from events import EventBus, Event, EventPriority, get_event_bus
from shared.src.lib.database import resource_locks_db


class LockStatus(Enum):
    """Resource lock status"""
    AVAILABLE = "available"
    LOCKED = "locked"
    QUEUED = "queued"


@dataclass
class ResourceLock:
    """Resource lock information"""
    resource_id: str
    resource_type: str
    owner_id: str
    owner_type: str
    acquired_at: datetime
    expires_at: datetime
    priority: int
    team_id: str = 'default'


class ResourceLockManager:
    """
    Resource Lock Manager
    
    Provides exclusive lock acquisition and priority-based queuing.
    Integrates with Event Bus to notify on lock changes.
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        """
        Initialize Resource Lock Manager
        
        Args:
            event_bus: Event bus for publishing lock events (optional)
        """
        self.event_bus = event_bus or get_event_bus()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start periodic cleanup of expired locks"""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        print("[@lock_manager] ✅ Started periodic cleanup")
    
    async def stop(self):
        """Stop cleanup task"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        print("[@lock_manager] Stopped")
    
    async def acquire(
        self, 
        resource_id: str, 
        resource_type: str,
        owner_id: str,
        owner_type: str = 'agent',
        timeout_seconds: int = 3600, 
        priority: int = 3,
        team_id: str = 'default'
    ) -> bool:
        """
        Try to acquire lock on resource
        
        Args:
            resource_id: Resource identifier (e.g., 'device1', 'tree_abc')
            resource_type: Resource type ('device', 'tree', 'userinterface')
            owner_id: Lock owner identifier
            owner_type: Owner type ('agent', 'user', 'system')
            timeout_seconds: Lock duration in seconds
            priority: Lock priority (lower = higher priority)
            team_id: Team namespace
            
        Returns:
            True if lock acquired, False if queued
        """
        # Clean up expired locks first (sync call)
        resource_locks_db.cleanup_expired_locks()
        
        # Try to acquire lock (sync call)
        lock_id = resource_locks_db.acquire_lock(
            resource_id=resource_id,
            resource_type=resource_type,
            owner_id=owner_id,
            owner_type=owner_type,
            timeout_seconds=timeout_seconds,
            priority=priority,
            team_id=team_id
        )
        
        if lock_id:
            # Publish event
            expires_at = datetime.utcnow() + timedelta(seconds=timeout_seconds)
            await self.event_bus.publish(Event(
                type="resource.acquired",
                payload={
                    "resource_id": resource_id,
                    "resource_type": resource_type,
                    "owner_id": owner_id,
                    "expires_at": expires_at.isoformat()
                },
                priority=EventPriority.NORMAL,
                team_id=team_id
            ))
            
            return True
        
        # Resource locked - add to queue (sync call)
        resource_locks_db.add_to_queue(
            resource_id=resource_id,
            owner_id=owner_id,
            priority=priority,
            timeout_seconds=timeout_seconds,
            team_id=team_id
        )
        
        # Publish queued event
        await self.event_bus.publish(Event(
            type="resource.queued",
            payload={
                "resource_id": resource_id,
                "owner_id": owner_id,
                "priority": priority
            },
            priority=EventPriority.NORMAL,
            team_id=team_id
        ))
        
        return False
    
    async def release(
        self, 
        resource_id: str, 
        owner_id: str,
        team_id: str = 'default'
    ) -> bool:
        """
        Release lock on resource
        
        Args:
            resource_id: Resource identifier
            owner_id: Lock owner (must match)
            team_id: Team namespace
            
        Returns:
            True if released, False if not locked or wrong owner
        """
        # Release lock (sync call)
        released = resource_locks_db.release_lock(resource_id, owner_id, team_id)
        
        if not released:
            return False
        
        # Publish event
        await self.event_bus.publish(Event(
            type="resource.released",
            payload={
                "resource_id": resource_id,
                "owner_id": owner_id
            },
            priority=EventPriority.NORMAL,
            team_id=team_id
        ))
        
        # Process queue for this resource
        await self._process_queue(resource_id, team_id)
        
        return True
    
    def is_available(self, resource_id: str) -> bool:
        """
        Check if resource is available
        
        Args:
            resource_id: Resource identifier
            
        Returns:
            True if available, False if locked
        """
        return resource_locks_db.is_resource_available(resource_id)
    
    def get_status(
        self, 
        resource_id: str,
        team_id: str = 'default'
    ) -> Dict:
        """
        Get current status of resource
        
        Args:
            resource_id: Resource identifier
            team_id: Team namespace
            
        Returns:
            Dictionary with status, owner, and queue information
        """
        return resource_locks_db.get_lock_status(resource_id, team_id)
    
    async def _process_queue(self, resource_id: str, team_id: str):
        """Process queue for released resource"""
        # Get next in queue (sync call)
        next_request = resource_locks_db.get_next_in_queue(resource_id, team_id)
        
        if next_request:
            # Notify the waiting owner that resource is ready
            await self.event_bus.publish(Event(
                type="resource.ready",
                payload={
                    "resource_id": resource_id,
                    "owner_id": next_request['owner_id']
                },
                priority=EventPriority.HIGH,
                team_id=team_id
            ))
            
            print(f"[@lock_manager] 🔔 Ready: {resource_id} for {next_request['owner_id']}")
    
    async def _periodic_cleanup(self):
        """Periodic cleanup task (runs every 30 seconds)"""
        while self._running:
            try:
                await asyncio.sleep(30)
                
                # Cleanup expired locks (sync call)
                expired = resource_locks_db.cleanup_expired_locks()
                
                if expired:
                    print(f"[@lock_manager] 🧹 Cleaned up {len(expired)} expired locks")
                    
                    # Process queues for released resources
                    for lock in expired:
                        await self._process_queue(lock['resource_id'], 'default')
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[@lock_manager] ❌ Cleanup error: {e}")


# Global instance
_lock_manager: Optional[ResourceLockManager] = None

def get_lock_manager() -> ResourceLockManager:
    """Get or create global lock manager instance"""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = ResourceLockManager()
    return _lock_manager

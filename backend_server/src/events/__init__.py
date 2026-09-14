"""
Event System for Multi-Agent Platform

This module provides event-driven architecture components:
- Event Bus: Central pub/sub system (Redis)
- Event Router: Routes events to appropriate agents
- Event Sources: Generate events from various triggers
"""

from .event_bus import EventBus, Event, EventPriority, get_event_bus
from .event_router import EventRouter, get_event_router

__all__ = ['EventBus', 'Event', 'EventPriority', 'get_event_bus', 'EventRouter', 'get_event_router']


"""Shared data models for VirtualPyTest services."""

# Device model should only be imported explicitly by backend_host
# from .device import *  # REMOVED: Causes backend_host imports in server context

# Device types are safe for server use (no backend_host dependencies)
from .device_types import *

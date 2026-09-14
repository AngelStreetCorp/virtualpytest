"""
Custom exception classes for navigation system
Provides specific error types for fail-early behavior
"""

class NavigationError(Exception):
    """Base class for navigation errors"""
    pass

class NavigationTreeError(NavigationError):
    """Tree loading and hierarchy errors"""
    pass

class UnifiedCacheError(NavigationError):
    """Unified cache population and retrieval errors"""
    pass

class PathfindingError(NavigationError):
    """Pathfinding and route calculation errors"""
    pass

class CrossTreeNavigationError(NavigationError):
    """Cross-tree navigation specific errors"""
    pass

class DatabaseError(NavigationError):
    """Database operation errors"""
    pass
"""
Resource Management for Multi-Agent Platform

This module provides resource locking and queue management
to enable safe parallel execution across multiple agents.
"""

from .lock_manager import ResourceLockManager, LockStatus, get_lock_manager

__all__ = ['ResourceLockManager', 'LockStatus', 'get_lock_manager']


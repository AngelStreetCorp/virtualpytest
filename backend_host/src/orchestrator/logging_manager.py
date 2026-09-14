"""
Logging Manager
Handles log capture for all execution types with context isolation
"""

import io
import sys
import asyncio
import inspect
import threading
from typing import Callable, Any, Dict
from contextvars import ContextVar

# Context variable for isolated log buffer (async-safe)
_log_context: ContextVar[io.StringIO] = ContextVar('log_context', default=None)


class ContextualTee:
    """
    Write to terminal AND context-specific log buffer (if active).
    Prevents log pollution from parallel executions.
    """
    def __init__(self, original_stream, is_stdout=True):
        self.original_stream = original_stream
        self.is_stdout = is_stdout
    
    def write(self, data):
        """Write to original stream + context buffer if exists"""
        # Always write to original (terminal/systemd)
        try:
            self.original_stream.write(data)
            self.original_stream.flush()
        except (IOError, OSError):
            pass
        
        # Also write to context buffer if active (for this specific execution)
        log_buffer = _log_context.get()
        if log_buffer is not None:
            try:
                log_buffer.write(data)
            except (IOError, OSError):
                pass
    
    def flush(self):
        """Flush both streams"""
        try:
            self.original_stream.flush()
        except (IOError, OSError):
            pass
        
        log_buffer = _log_context.get()
        if log_buffer:
            try:
                log_buffer.flush()
            except (IOError, OSError):
                pass


# Global contextual streams (installed once at module load)
_contextual_stdout = None
_contextual_stderr = None
_original_stdout = sys.stdout
_original_stderr = sys.stderr
_install_lock = threading.Lock()


def _ensure_contextual_streams_installed():
    """Install contextual streams once (idempotent)"""
    global _contextual_stdout, _contextual_stderr
    
    with _install_lock:
        if _contextual_stdout is None:
            _contextual_stdout = ContextualTee(_original_stdout, is_stdout=True)
            _contextual_stderr = ContextualTee(_original_stderr, is_stdout=False)
            sys.stdout = _contextual_stdout
            sys.stderr = _contextual_stderr


class LoggingManager:
    """Manages log capture with context isolation"""
    
    @staticmethod
    async def execute_with_logging(execution_fn: Callable, *args, **kwargs) -> Dict[str, Any]:
        """
        Execute function and capture ONLY its logs (context-isolated).
        Parallel executions won't pollute each other's logs.
        
        Args:
            execution_fn: Function to execute (sync or async)
            *args, **kwargs: Arguments to pass to execution_fn
            
        Returns:
            Dict with execution result + 'logs' field (only this execution's logs)
        """
        # Ensure contextual streams are installed
        _ensure_contextual_streams_installed()
        
        # Create isolated log buffer for THIS execution only
        log_buffer = io.StringIO()
        
        # Set context variable (async-safe, won't affect other executions)
        token = _log_context.set(log_buffer)
        
        try:
            print(f"[@LoggingManager] Log capture started (context-isolated)", flush=True)
            
            # Execute the function
            if inspect.iscoroutinefunction(execution_fn) or asyncio.iscoroutine(execution_fn):
                result = await execution_fn(*args, **kwargs)
            else:
                result = execution_fn(*args, **kwargs)
            
            print(f"[@LoggingManager] Log capture completed", flush=True)
            
            # Ensure result is a dict
            if not isinstance(result, dict):
                result = {'success': False, 'error': 'Invalid result type'}
            
            # Flush and capture logs from THIS execution only
            sys.stdout.flush()
            sys.stderr.flush()
            result['logs'] = log_buffer.getvalue()
            
            return result
            
        finally:
            # Reset context variable (cleanup)
            _log_context.reset(token)
